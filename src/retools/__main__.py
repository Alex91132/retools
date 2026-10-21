# -*- coding: utf-8 -*-
"""CLI retools: расчёт добычи, факторный анализ, PVT-свойства.

Использование:
    python -m retools calc --book RE_Tools.xlsx --well 1 --months 60
    python -m retools calc --perm 250 --h 20 --phi 0.18 --sw 0.3 --pres 110 --pwf 50
    python -m retools fa --base 200,10,150,80,120 --new 210,0,170,90,110
    python -m retools pvt --pressure 110
"""
import argparse
import sys

from .gtm_io import GtmWell, read_gtm
from .fa import Scenario, decompose
from .cpvt import CPVT


def cmd_calc(args):
    """Расчёт профиля добычи."""
    from .production import produce

    if args.book:
        wells = read_gtm(args.book)
        if not wells:
            print("Ошибка: рейтинг ГТМ пуст")
            return 1
        idx = min(args.well, len(wells)) - 1
        w = wells[idx]
        print(f"Скважина: {w.well} ({w.field}, {w.target_zone}), "
              f"ГТМ: {w.gtm}, заканчивание: {w.completion}")
    else:
        w = GtmWell(
            h_eff=args.h, perm=args.perm, phi=args.phi, sw_init=args.sw,
            p_res_init=args.pres, p_wf_target=args.pwf, flood_share=args.flood,
            r_contour=args.rcontour, operation_factor=0.95,
            q_min=args.qmin, wc_limit=98, oip=500.0,
        )
        print(f"Параметры: h={args.h}м, k={args.perm}мД, φ={args.phi}, "
              f"Sw={args.sw}, Pпл={args.pres}атм, Pзаб={args.pwf}атм")

    profile = produce(w, n_months=args.months)

    # заголовок
    print(f"\n{'Мес':>4} {'Рпл':>7} {'Qж':>8} {'Qн':>8} {'Обв':>6} {'Кум.нефть':>10}")
    print("-" * 50)
    for m in profile.months:
        print(f"{m.month:4d} {m.p_res:7.1f} {m.q_liq:8.1f} {m.q_oil:8.1f} "
              f"{m.water_cut:5.1f}% {m.cum_oil:10.0f}")

    # итог
    total = profile.months[-1]
    print(f"\nИтого за {args.months} мес: "
          f"Qн(мес1)={profile.months[0].q_oil:.0f} → Qн(мес{args.months})={total.q_oil:.0f} м³/сут, "
          f"накоплено {total.cum_oil:.0f} м³ нефти")
    return 0


def cmd_fa(args):
    """Факторный анализ."""
    base_vals = [float(v) for v in args.base.split(",")]
    new_vals = [float(v) for v in args.new.split(",")]
    if len(base_vals) != 5 or len(new_vals) != 5:
        print("Ошибка: нужно 5 параметров через запятую: Qж,обв,Qн,Рзаб,Рпл")
        return 1

    base = Scenario(q_liq=base_vals[0], water_cut=base_vals[1], q_oil=base_vals[2],
                    p_wf=base_vals[3], p_res=base_vals[4])
    new = Scenario(q_liq=new_vals[0], water_cut=new_vals[1], q_oil=new_vals[2],
                   p_wf=new_vals[3], p_res=new_vals[4])

    res = decompose(base, new)
    print(f"\nРазложение ΔQн = {res.delta_q_oil:.1f} м³/сут:")
    print(f"{'Фактор':20s} {'Вклад':>10s}")
    print("-" * 32)
    for name, val in [("Обводнённость", res.water_cut), ("Рпл", res.p_res),
                      ("Рзаб", res.p_wf), ("Кпр", res.pi)]:
        print(f"{name:20s} {val:+10.2f}")
    print(f"{'Сумма':20s} {res.total:+10.2f}")
    print(f"{'Невязка':20s} {res.balance_error:+10.6f}")
    return 0


def cmd_pvt(args):
    """PVT-свойства при заданном давлении."""
    fluid = CPVT(gamma_gas=0.7, gamma_oil=0.9, gamma_wat=1.01, rsb_m3m3=60,
                 pb_atma=159, bob_m3m3=1.08, muob_cP=8.8, corr=1, t_res_C=32)
    print(f"\nPVT при P={args.pressure} атм, T=32°C (контрольный флюид):")
    print(f"{'Параметр':25s} {'Значение':>12s}")
    print("-" * 38)
    for p in [50, 80, 110, 140, 159, 180, 220, 300]:
        props = fluid.calc(p, 32)
        marker = " ←" if abs(p - args.pressure) < 1 else ""
        print(f"P={p:3d}: Rs={props['rs']:6.1f} Bo={props['bo']:.4f} "
              f"Bg={props['bg']:.5f} µo={props['mu_oil']:.2f} z={props['z']:.3f}{marker}")
    return 0


def cmd_info(args):
    """Информация о пакете."""
    import retools
    print(f"retools {retools.__version__}")
    print("Порт расчётника RE Tools (Excel/VBA) на Python.")
    print("Модули: fa, jd, intervals, cpvt, pvt_mbe, pallets, production")
    print("\nКоманды:")
    print("  calc  — расчёт профиля добычи")
    print("  fa    — факторный анализ отклонений Qн")
    print("  pvt   — PVT-свойства при заданном давлении")
    print("  info  — эта справка")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="retools",
                                     description="Порт RE Tools на Python")
    sub = parser.add_subparsers(dest="command")

    # calc
    p_calc = sub.add_parser("calc", help="расчёт профиля добычи")
    p_calc.add_argument("--book", help="путь к книге RE Tools (.xlsm)")
    p_calc.add_argument("--well", type=int, default=1, help="№ скважины в рейтинге")
    p_calc.add_argument("--months", type=int, default=24, help="месяцев прогноза")
    # параметры скважины (если без --book)
    p_calc.add_argument("--perm", type=float, default=250, help="проницаемость, мД")
    p_calc.add_argument("--h", type=float, default=20, help="эфф. мощность, м")
    p_calc.add_argument("--phi", type=float, default=0.18, help="пористость")
    p_calc.add_argument("--sw", type=float, default=0.3, help="нач. водонасыщенность")
    p_calc.add_argument("--pres", type=float, default=110, help="нач. Рпл, атм")
    p_calc.add_argument("--pwf", type=float, default=50, help="целевое Рзаб, атм")
    p_calc.add_argument("--flood", type=float, default=0.5, help="доля заводняемых толщин")
    p_calc.add_argument("--rcontour", type=float, default=400, help="R контура, м")
    p_calc.add_argument("--qmin", type=float, default=1, help="мин. дебит, м³/сут")

    # fa
    p_fa = sub.add_parser("fa", help="факторный анализ")
    p_fa.add_argument("--base", required=True,
                      help="базовый сценарий: Qж,обв,Qн,Рзаб,Рпл")
    p_fa.add_argument("--new", required=True,
                      help="новый сценарий: Qж,обв,Qн,Рзаб,Рпл")

    # pvt
    p_pvt = sub.add_parser("pvt", help="PVT-свойства")
    p_pvt.add_argument("--pressure", type=float, default=110, help="давление, атм")

    sub.add_parser("info", help="справка")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    handlers = {"calc": cmd_calc, "fa": cmd_fa, "pvt": cmd_pvt, "info": cmd_info}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
