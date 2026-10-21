# -*- coding: utf-8 -*-
"""Подбор компоновки ГС/МЗС: фильтры, глухая труба, пакеры-эластомеры.

В RE Tools это делал макрос AutoCalcFilter: «Поиск решения» (эволюционный метод)
двигал до 10 пар кровля–подошва и максимизировал суммарный Qн при ограничениях
(длина фильтра, обводнённость каждого фильтра ≤ предела). Эволюционный поиск
не гарантирует оптимум — на контрольной скважине он давал Qн 46,3 т/сут при
пределе 0 % и 329,3 при 5–98 %.

Здесь та же задача решается точно — динамическим программированием по срезам:
дебиты срезов складываются (как в таблицах Qж/Qн книги), ограничения линейны:
- фильтр не короче min_filter;
- между фильтрами не меньше min_gap (там глухая труба и пакеры);
- не больше max_filters фильтров;
- обводнённость каждого фильтра ≤ max_wc:  Qн ≥ (1 − wc)·ρ·Qж.

Взаимовлияние секций ГС (коэффициент CA зависит от суммарной длины фильтров)
учитывается итерациями: длина → дебиты срезов → оптимум → новая длина, пока
компоновка не перестанет меняться.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np

from .field_object import FieldObject, JdSectionPallets
from .rigis import RigisCase, SliceResult, compute


@dataclass
class Filter:
    top: float
    bottom: float
    q_liq: float
    q_oil: float
    water_cut: float      # %, объёмная — как на листе: 100 − Qн/(ρ·Qж)·100

    @property
    def length(self) -> float:
        return self.bottom - self.top


@dataclass
class Isolation:
    """Участок между фильтрами (или до/после них), который закрывается."""
    top: float
    bottom: float
    q_liq: float          # потенциал, если бы участок работал
    q_oil: float
    water_cut: float
    reason: str           # «вода», «газ», «неколлектор», «перемычка»
    packers: list = field(default_factory=list)   # (кровля, подошва) эластомеров


@dataclass
class Completion:
    filters: list
    isolations: list
    q_liq: float
    q_oil: float
    water_cut: float
    l_total: float
    max_wc: float
    iterations: int
    slices: list          # SliceResult при итоговой длине фильтров


def _water_cut(q_oil: float, q_liq: float, rho: float) -> float:
    return 0.0 if q_liq <= 0 else max(0.0, 100 - q_oil / rho / q_liq * 100)


def _dp_table(tops, bots, ql, qo, rho, max_wc, min_filter, min_gap, max_filters,
              weight=None, per_filter_wc=True, forbidden=None, filter_cost=0.0):
    """ДП по одному стволу: лучший результат при ровно k фильтрах и восстановление.

    Концы фильтра — только работающие срезы (Qж > 0): глухая труба по краям
    фильтра бессмысленна, а над ПГМЦ срезы не работают вовсе.
    weight — целевая функция по срезам (по умолчанию Qн); per_filter_wc —
    предел обводнённости для каждого фильтра; forbidden — срезы, которые
    нельзя вскрывать (отступ от газа и т. п.); filter_cost — «цена» фильтра в
    единицах цели: фильтр ставится, только если даёт больше.

    Векторизовано матрицей «начало i × конец j» (допустимость не зависит от
    числа фильтров k): f[k, j] = max(f[k, j−1], max_i (f[k−1, p(i)] − W[i−1]) + W[j]).
    Возвращает (fk, recon): fk[k] — лучшее значение при k фильтрах (−inf, если
    невозможно), recon(k) — список отрезков (i, j) срезов.
    """
    n = len(tops)
    NEG = -1e18
    if n == 0:
        return np.array([0.0] + [NEG] * max_filters), (lambda k: [])
    live = np.asarray(ql) > 0
    QL = np.concatenate([[0.0], np.cumsum(ql)])
    QO = np.concatenate([[0.0], np.cumsum(qo)])
    W = QO if weight is None else np.concatenate([[0.0], np.cumsum(weight)])
    tops_a, bots_a = np.asarray(tops, dtype=float), np.asarray(bots, dtype=float)
    I = np.arange(1, n + 1)[:, None]          # начало (1..n)
    J = np.arange(1, n + 1)[None, :]          # конец (1..n)
    q_o = QO[J] - QO[I - 1]
    ok = (J >= I) & (bots_a[J - 1] - tops_a[I - 1] >= min_filter - 1e-9) & (q_o > 0)
    ok &= live[I - 1] & live[J - 1]
    if per_filter_wc:
        a = 1 - max_wc / 100.0
        ok &= q_o >= a * rho * (QL[J] - QL[I - 1]) - 1e-12
    if forbidden is not None:
        FB = np.concatenate([[0], np.cumsum(np.asarray([bool(x) for x in forbidden], dtype=int))])
        ok &= (FB[J] - FB[I - 1]) == 0
    bots_list = list(bots)
    p = np.array([bisect_right(bots_list, tops[i] - min_gap + 1e-9) for i in range(n)])   # для начала i+1
    f = np.full((max_filters + 1, n + 1), NEG)
    f[0, :] = 0.0
    start = np.full((max_filters + 1, n + 1), -1, dtype=int)    # начало фильтра, кончающегося ровно в j
    ends = np.full((max_filters + 1, n + 1), NEG)               # значение, если фильтр кончается ровно в j
    for k in range(1, max_filters + 1):
        prev = f[k - 1][p]
        A = np.where(prev > NEG / 2, prev - W[:-1], NEG)       # A[i-1] для начала i
        M = np.where(ok, A[:, None] + W[None, 1:] - filter_cost, NEG)   # (i, j)
        best_i = np.argmax(M, axis=0)
        best = M[best_i, np.arange(n)]
        ends[k, 1:] = best
        f[k] = np.maximum.accumulate(np.concatenate([[NEG], best]))
        start[k, 1:] = np.where(best > NEG / 2, best_i + 1, -1)

    def recon(k):
        out, j = [], n
        while k > 0 and j > 0:
            target = f[k, j]
            if target <= NEG / 2:
                return []
            while j > 0 and not (start[k, j] > 0 and ends[k, j] >= target - 1e-9 * max(1.0, abs(target))):
                j -= 1
            if j == 0:
                break
            i = start[k, j]
            out.append((i - 1, j - 1))
            j = int(p[i - 1])
            k -= 1
        return sorted(out)

    return f[:, n].copy(), recon


def _dp(tops, bots, ql, qo, rho, max_wc, min_filter, min_gap, max_filters,
        weight=None, per_filter_wc=True, forbidden=None):
    """Оптимальный набор отрезков одного ствола: (отрезки, значение цели)."""
    fk, recon = _dp_table(tops, bots, ql, qo, rho, max_wc, min_filter, min_gap, max_filters,
                          weight, per_filter_wc, forbidden)
    k = int(np.argmax(fk))
    return recon(k), float(fk[k])


def _summ(sl, res, i0, i1):
    ql = sum(r.q_liq for r in res[i0:i1 + 1])
    qo = sum(r.q_oil for r in res[i0:i1 + 1])
    return ql, qo


def _isolation_reason(sl, res, i0, i1, rho, max_wc=50.0, forbidden=None) -> str:
    seg = list(range(i0, i1 + 1))
    if not seg:
        return "перемычка"
    gas = sum(sl[i].h for i in seg if sl[i].is_gas)
    coll = sum(sl[i].h for i in seg if res[i].used)
    ql = sum(res[i].q_liq for i in seg)
    qo = sum(res[i].q_oil for i in seg)
    if gas > 0.5 * sum(sl[i].h for i in seg):
        return "газ"
    if forbidden is not None:
        why = next((forbidden[i] for i in seg if forbidden[i]), "")
        if why:
            return why if isinstance(why, str) else "отступ от газа"
    if coll == 0 or ql <= 0:
        return "неколлектор"
    return "вода" if _water_cut(qo, ql, rho) > max_wc else "перемычка"


def forbidden_near_gas(slices, offset: float) -> list[str]:
    """Срезы ближе offset м (по стволу) к газонасыщенным (характер насыщения «газ»)."""
    if offset <= 0:
        return [""] * len(slices)
    gas = [(s.top - offset, s.bottom + offset) for s in slices if s.is_gas]
    return ["отступ от газа" if any(s.bottom > a and s.top < b for a, b in gas) else "" for s in slices]


def forbidden_mask(slices, gas_offset: float = 0.0, goc_tvd: float | None = None, goc_offset: float = 0.0,
                   owc_tvd: float | None = None, owc_offset: float = 0.0) -> list[str]:
    """Причина запрета вскрытия среза ('' — можно): отступ от газа по стволу,
    от ГНК и ВНК по абсолютной отметке (АО растёт вниз; нужны колонки АО выгрузки)."""
    out = forbidden_near_gas(slices, gas_offset)
    for k, s in enumerate(slices):
        if out[k] or s.bottom_tvd <= 0:
            continue
        if goc_tvd is not None and s.top_tvd < goc_tvd + goc_offset:
            out[k] = "отступ от ГНК"
        elif owc_tvd is not None and s.bottom_tvd > owc_tvd - owc_offset:
            out[k] = "отступ от ВНК"
    return out


@dataclass
class _Lateral:
    """Ствол в подборе: срезы и их дебиты при текущей длине фильтров."""
    tops: list
    bots: list
    ql: np.ndarray
    qo: np.ndarray
    forbidden: list


def _combine(tables, max_filters):
    """Распределить число фильтров между стволами: max Σ fk_c[k_c], Σ k_c ≤ max_filters."""
    NEG = -1e18
    best = {0: (0.0, [])}
    for fk, _ in tables:
        new = {}
        for tot, (val, ks) in best.items():
            for k in range(0, max_filters - tot + 1):
                if fk[k] <= NEG / 2:
                    continue
                t, v = tot + k, val + fk[k]
                if t not in new or v > new[t][0]:
                    new[t] = (v, ks + [k])
        best = new
    _, (val, ks) = max(best.items(), key=lambda kv: kv[1][0])
    return [recon(k) for (_, recon), k in zip(tables, ks)]


def _choose_multi(lats, rho, max_wc, rules, max_filters, wc_mode, filter_cost=0.0, base=None):
    """Отрезки по всем стволам: предел обводнённости по фильтру или по скважине в целом.

    base — цель по срезам каждого ствола (по умолчанию начальный Qн).
    """
    base = base or [None] * len(lats)
    def tables(weights, per_filter):
        return [_dp_table(l.tops, l.bots, l.ql, l.qo, rho, max_wc if per_filter else 100.0, rules.min_filter,
                          rules.min_gap, max_filters, weight=w, per_filter_wc=per_filter, forbidden=l.forbidden,
                          filter_cost=filter_cost)
                for l, w in zip(lats, weights)]

    if wc_mode == "filter":
        return _combine(tables(base, True), max_filters)
    # по скважине: max ΣQн при ΣQн ≥ c·ΣQж — множитель Лагранжа μ, бисекция
    c = (1 - max_wc / 100.0) * rho
    gs = [l.qo - c * l.ql for l in lats]

    def solve(mu):
        segs = _combine(tables([(l.qo if b is None else b) + mu * g for l, g, b in zip(lats, gs, base)], False),
                        max_filters)
        slack = sum(g[a:b + 1].sum() for g, sg in zip(gs, segs) for a, b in sg)
        return segs, slack

    segs, slack = solve(0.0)
    if slack >= -1e-9:
        return segs
    lo, hi = 0.0, 1.0
    s_hi, sl_hi = solve(hi)
    while sl_hi < -1e-9 and hi < 1e6:
        hi *= 4
        s_hi, sl_hi = solve(hi)
    if sl_hi < -1e-9:
        return [[] for _ in lats]
    best = s_hi
    for _ in range(40):
        if hi - lo <= 1e-3 * max(hi, 1e-6):
            break
        mid = (lo + hi) / 2
        s_mid, sl_mid = solve(mid)
        if sl_mid >= -1e-9:
            hi, best = mid, s_mid
        else:
            lo = mid
    return best


def _build_completion(case, res, segs, rho, max_wc, forbidden, l_total, iterations) -> Completion:
    """Фильтры, изоляция с пакерами и итоги одного ствола по выбранным отрезкам."""
    rules, sl = case.rules, case.slices
    tops = [s.top for s in sl]
    bots = [s.bottom for s in sl]
    filters = []
    for a, b in segs:
        ql, qo = _summ(sl, res, a, b)
        filters.append(Filter(tops[a], bots[b], ql, qo, _water_cut(qo, ql, rho)))
    isolations = []
    first_used = next((k for k, r in enumerate(res) if r.used), None)
    last_used = max((k for k, r in enumerate(res) if r.used), default=None)
    bounds = [(-1, -1)] + list(segs) + [(len(sl), len(sl))]
    for (a0, b0), (a1, b1) in zip(bounds, bounds[1:]):
        i0, i1 = b0 + 1, a1 - 1
        if first_used is not None:
            i0 = max(i0, first_used)
            i1 = min(i1, last_used)
        if i1 < i0:
            continue
        ql, qo = _summ(sl, res, i0, i1)
        iso = Isolation(tops[i0], bots[i1], ql, qo, _water_cut(qo, ql, rho),
                        _isolation_reason(sl, res, i0, i1, rho, max_wc, forbidden))
        # пакеры у границ соседних фильтров: отступ elastomer_offset, длина elastomer
        off, el = rules.elastomer_offset, rules.elastomer
        upper = bots[b0] if b0 >= 0 else None          # подошва фильтра сверху
        lower = tops[a1] if a1 < len(sl) else None     # кровля фильтра снизу
        if upper is not None and lower is not None and lower - upper < 2 * (off + el):
            # короткий промежуток: два пакера с отступами не помещаются — один посередине
            mid = (upper + lower) / 2
            iso.packers.append((mid - el / 2, mid + el / 2))
        else:
            if upper is not None:
                iso.packers.append((upper + off, upper + off + el))
            if lower is not None:
                iso.packers.append((lower - off - el, lower - off))
        isolations.append(iso)
    ql = sum(f.q_liq for f in filters)
    qo = sum(f.q_oil for f in filters)
    return Completion(filters, isolations, ql, qo, _water_cut(qo, ql, rho), l_total, max_wc, iterations, res)


@dataclass
class WellCompletion:
    """Компоновка скважины из нескольких стволов (МЗС); для ГС — один ствол."""
    laterals: list          # Completion по стволам
    names: list
    q_liq: float
    q_oil: float
    water_cut: float
    l_total: float
    max_wc: float
    iterations: int


def plan_multi(cases: list, obj: FieldObject, pallets: JdSectionPallets, max_wc: float | None = None,
               max_filters: int = 10, zones: list | None = None, max_iter: int = 8, wc_mode: str = "filter",
               gas_offset: float = 0.0, names: list | None = None, filter_cost: float = 0.0,
               goc_tvd: float | None = None, goc_offset: float = 0.0, owc_tvd: float | None = None,
               owc_offset: float = 0.0, weights: list | None = None) -> WellCompletion:
    """Совместный подбор по стволам МЗС (общие: число фильтров, длина секций, предел по скважине).

    Коэффициент секции ГС зависит от суммарной эффективной длины фильтров
    всех стволов — она общая и уточняется итерациями. filter_cost — минимальный
    прирост Qн на фильтр, т/сут (фильтр с меньшим приростом не ставится).
    weights — своя цель по срезам каждого ствола вместо начального Qн (например,
    накопленная нефть или NPV среза, см. lifetime); filter_cost — в её единицах.
    Ограничения по обводнённости — по начальным дебитам.
    """
    rules = cases[0].rules
    max_wc = rules.max_wc if max_wc is None else max_wc
    rho = obj.rho_oil
    zones = zones or [None] * len(cases)
    forb = [forbidden_mask(c.slices, gas_offset, goc_tvd, goc_offset, owc_tvd, owc_offset) for c in cases]
    l_total = sum(s.h for c, z in zip(cases, zones) for s, r in zip(c.slices, compute(c, obj, pallets, z)) if r.used)
    chosen, seen, it = None, set(), 0
    for it in range(1, max_iter + 1):
        ress = [compute(c, obj, pallets, z, l_total=max(l_total, 1e-6)) for c, z in zip(cases, zones)]
        lats = [_Lateral([s.top for s in c.slices], [s.bottom for s in c.slices],
                         np.array([r.q_liq for r in res]), np.array([r.q_oil for r in res]), fb)
                for c, res, fb in zip(cases, ress, forb)]
        segs = _choose_multi(lats, rho, max_wc, rules, max_filters, wc_mode, filter_cost,
                             None if weights is None else [np.asarray(w, dtype=float) for w in weights])
        new_l = sum(c.slices[k].h for c, res, sg in zip(cases, ress, segs) for a, b in sg for k in range(a, b + 1)
                    if res[k].used)
        key = tuple(tuple(s) for s in segs)
        if key == chosen or key in seen:
            chosen = key
            break
        seen.add(key)
        chosen, l_total = key, new_l
    ress = [compute(c, obj, pallets, z, l_total=max(l_total, 1e-6)) for c, z in zip(cases, zones)]
    comps = [_build_completion(c, res, list(sg), rho, max_wc, fb, l_total, it)
             for c, res, sg, fb in zip(cases, ress, chosen, forb)]
    ql = sum(c.q_liq for c in comps)
    qo = sum(c.q_oil for c in comps)
    names = names or [c.slices[0].well if c.slices else f"ствол {i + 1}" for i, c in enumerate(cases)]
    return WellCompletion(comps, names, ql, qo, _water_cut(qo, ql, rho), l_total, max_wc, it)


def plan(case: RigisCase, obj: FieldObject, pallets: JdSectionPallets, max_wc: float | None = None,
         max_filters: int = 10, zones=None, max_iter: int = 8, wc_mode: str = "filter",
         gas_offset: float = 0.0, filter_cost: float = 0.0, **contacts) -> Completion:
    """Оптимальная компоновка ствола ГС при пределе обводнённости max_wc, %.

    wc_mode — "filter": предел для каждого фильтра (как в книге); "well": для
    скважины в целом (фильтры по отдельности могут быть обводнённее).
    gas_offset — минимальное расстояние от фильтров до газонасыщенных срезов, м.
    contacts — goc_tvd / goc_offset, owc_tvd / owc_offset: отступы от ГНК и ВНК по АО, м.
    zones — интервалы параметров пласта (блок «Выбор»); по умолчанию — из case.
    """
    w = plan_multi([case], obj, pallets, max_wc, max_filters, [zones], max_iter, wc_mode, gas_offset,
                   filter_cost=filter_cost, **contacts)
    return w.laterals[0]


def wc_curve(case, obj, pallets, limits=(0, 5, 10, 20, 30, 40, 50, 70, 90, 95, 98, 100), **kw) -> list[Completion]:
    """Кривая «максимальный Qн против предела обводнённости» (AutoCalcALLFilters книги)."""
    return [plan(case, obj, pallets, max_wc=lim, **kw) for lim in limits]


def evaluate(case, obj, pallets, filters_ranges, zones=None) -> Completion:
    """Оценка заданной вручную компоновки (те же правила подсчёта)."""
    rho = obj.rho_oil
    sl = case.slices
    first = compute(case, obj, pallets, zones)
    inside = lambda s: any(t <= s.top and s.bottom <= b for t, b in filters_ranges)   # noqa: E731
    l_total = sum(s.h for s, r in zip(sl, first) if r.used and inside(s))
    res = compute(case, obj, pallets, zones, l_total=max(l_total, 1e-6))
    filters = []
    for t, b in filters_ranges:
        idx = [k for k, s in enumerate(sl) if t <= s.top and s.bottom <= b]
        ql = sum(res[k].q_liq for k in idx)
        qo = sum(res[k].q_oil for k in idx)
        filters.append(Filter(t, b, ql, qo, _water_cut(qo, ql, rho)))
    ql = sum(f.q_liq for f in filters)
    qo = sum(f.q_oil for f in filters)
    return Completion(filters, [], ql, qo, _water_cut(qo, ql, rho), l_total, 100.0, 1, res)


@dataclass
class LinerElement:
    kind: str             # «фильтр» | «глухая труба» | «эластомер»
    top: float
    bottom: float

    @property
    def length(self) -> float:
        return self.bottom - self.top


def liner(c: Completion, rules, top: float | None = None, bottom: float | None = None) -> list[LinerElement]:
    """Раскладка хвостовика по глубине: фильтры, пакеры-эластомеры, глухая труба.

    top/bottom — границы хвостовика (по умолчанию от первого фильтра до последнего
    работающего среза). Пакеры берутся из плана изоляции, остальное между
    фильтрами — глухая труба.
    """
    if not c.filters:
        return []
    top = c.filters[0].top if top is None else top
    end = max(c.filters[-1].bottom, max((p1 for iso in c.isolations for _, p1 in iso.packers), default=0.0))
    end = end if bottom is None else max(end, bottom)
    marks = [LinerElement("фильтр", f.top, f.bottom) for f in c.filters]
    marks += [LinerElement("эластомер", p0, p1) for iso in c.isolations for p0, p1 in iso.packers]
    marks = sorted((m for m in marks if m.bottom > top), key=lambda m: m.top)
    out, cur = [], top
    for m in marks:
        if m.top > cur + 1e-6:
            out.append(LinerElement("глухая труба", cur, m.top))
        out.append(LinerElement(m.kind, max(m.top, cur), m.bottom))
        cur = max(cur, m.bottom)
    if end > cur + 1e-6:
        out.append(LinerElement("глухая труба", cur, end))
    return out


def wc_curve_multi(cases, obj, pallets, limits=(0, 5, 10, 20, 30, 40, 50, 70, 90, 95, 98, 100), **kw) -> list:
    """Кривая «Qн от предела обводнённости» для скважины из нескольких стволов."""
    return [plan_multi(cases, obj, pallets, max_wc=lim, **kw) for lim in limits]


def evaluate_multi(cases, obj, pallets, ranges_per_case, zones=None) -> WellCompletion:
    """Оценка заданной компоновки по стволам (общая длина секций)."""
    rho = obj.rho_oil
    zones = zones or [None] * len(cases)
    inside = lambda s, rr: any(t <= s.top and s.bottom <= b for t, b in rr)   # noqa: E731
    l_total = sum(s.h for c, z, rr in zip(cases, zones, ranges_per_case)
                  for s, r in zip(c.slices, compute(c, obj, pallets, z)) if r.used and inside(s, rr))
    comps = []
    for c, z, rr in zip(cases, zones, ranges_per_case):
        res = compute(c, obj, pallets, z, l_total=max(l_total, 1e-6))
        filters = []
        for t, b in rr:
            idx = [k for k, s in enumerate(c.slices) if t <= s.top and s.bottom <= b]
            ql = sum(res[k].q_liq for k in idx)
            qo = sum(res[k].q_oil for k in idx)
            filters.append(Filter(t, b, ql, qo, _water_cut(qo, ql, rho)))
        ql = sum(f.q_liq for f in filters)
        qo = sum(f.q_oil for f in filters)
        comps.append(Completion(filters, [], ql, qo, _water_cut(qo, ql, rho), l_total, 100.0, 1, res))
    ql = sum(c.q_liq for c in comps)
    qo = sum(c.q_oil for c in comps)
    names = [c.slices[0].well if c.slices else "" for c in cases]
    return WellCompletion(comps, names, ql, qo, _water_cut(qo, ql, rho), l_total, 100.0, 1)


def split_laterals(case: RigisCase) -> list:
    """Разбить срезы по стволам (столбец «скважина» выгрузки) с сохранением порядка."""
    from dataclasses import replace
    groups: dict = {}
    for s in case.slices:
        groups.setdefault(s.well or "", []).append(s)
    return [replace(case, slices=sl) for sl in groups.values()]


def manual_plan(cases: list, obj: FieldObject, pallets: JdSectionPallets, ranges_per_case: list,
                zones: list | None = None, max_wc: float = 100.0, gas_offset: float = 0.0,
                names: list | None = None, **contacts) -> tuple:
    """Компоновка по интервалам, заданным вручную (по стволам), — те же правила подсчёта, что у подбора.

    Фильтр вскрывает срезы, середина которых попадает в интервал (границы фильтра —
    по границам срезов); пересекающиеся интервалы объединяются. Возвращает
    (WellCompletion с изоляцией и пакерами, список замечаний по правилам
    компоновки: короткий фильтр, малый промежуток, газ, отступ от контактов).
    """
    rho = obj.rho_oil
    zones = zones or [None] * len(cases)
    notes: list[str] = []
    segs_all = []
    for ci, (c, rr) in enumerate(zip(cases, ranges_per_case)):
        mids = [(s.top + s.bottom) / 2 for s in c.slices]
        inside = [any(t <= m <= b for t, b in rr) for m in mids]
        segs, k = [], 0
        while k < len(inside):
            if inside[k]:
                j = k
                while j + 1 < len(inside) and inside[j + 1]:
                    j += 1
                segs.append((k, j))
                k = j + 1
            else:
                k += 1
        segs_all.append(segs)
        name = (names[ci] if names else (c.slices[0].well if c.slices else f"ствол {ci + 1}"))
        srt = sorted(rr)
        for (t0, b0), (t1, b1) in zip(srt, srt[1:]):
            if t1 < b0:
                notes.append(f"{name}: интервалы {t0:g}–{b0:g} и {t1:g}–{b1:g} м пересекаются — объединены в один фильтр")
        for t, b in srt:
            if not any(t <= m <= b for m in mids):
                notes.append(f"{name}: в интервал {t:g}–{b:g} м не попадает ни одна середина среза — фильтра нет")
        r = c.rules
        forb = forbidden_mask(c.slices, gas_offset, **contacts)
        for n, (a, b) in enumerate(segs, 1):
            top, bot = c.slices[a].top, c.slices[b].bottom
            if bot - top < r.min_filter - 1e-9:
                notes.append(f"{name}: фильтр {n} ({top:.1f}–{bot:.1f} м) короче {r.min_filter:g} м")
            why = {forb[i] for i in range(a, b + 1) if forb[i]}
            if why:
                notes.append(f"{name}: фильтр {n} ({top:.1f}–{bot:.1f} м) вскрывает запрещённые срезы: "
                             + ", ".join(sorted(why)))
            if any(c.slices[i].is_gas for i in range(a, b + 1)):
                notes.append(f"{name}: фильтр {n} ({top:.1f}–{bot:.1f} м) вскрывает газонасыщенные срезы")
        for (a0, b0), (a1, b1) in zip(segs, segs[1:]):
            gap = c.slices[a1].top - c.slices[b0].bottom
            if gap < r.min_gap - 1e-9:
                notes.append(f"{name}: промежуток {c.slices[b0].bottom:.1f}–{c.slices[a1].top:.1f} м ({gap:.1f} м) "
                             f"меньше {r.min_gap:g} м — пакеры не поместятся")
    first = [compute(c, obj, pallets, z) for c, z in zip(cases, zones)]
    l_total = sum(c.slices[i].h for c, res, sg in zip(cases, first, segs_all) for a, b in sg for i in range(a, b + 1)
                  if res[i].used)
    ress = [compute(c, obj, pallets, z, l_total=max(l_total, 1e-6)) for c, z in zip(cases, zones)]
    comps = [_build_completion(c, res, list(sg), rho, max_wc, forbidden_mask(c.slices, gas_offset, **contacts),
                               l_total, 1) for c, res, sg in zip(cases, ress, segs_all)]
    ql = sum(c.q_liq for c in comps)
    qo = sum(c.q_oil for c in comps)
    names = names or [c.slices[0].well if c.slices else f"ствол {i + 1}" for i, c in enumerate(cases)]
    return WellCompletion(comps, names, ql, qo, _water_cut(qo, ql, rho), l_total, max_wc, 1), notes
