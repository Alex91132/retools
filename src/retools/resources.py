# -*- coding: utf-8 -*-
"""Доступ к данным пакета: фикстуры и демонстрационные выгрузки.

Раньше код читал файлы из каталога `tests/` через `Path(__file__).parents[2]`.
Это работало только в исходниках: после `pip install` такого каталога нет, и
`default_pallets()` падал с FileNotFoundError. Теперь данные лежат внутри пакета
(`retools/data/`) и читаются через `importlib.resources`.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def data_dir() -> Path:
    """Каталог с данными пакета."""
    return Path(str(files("retools").joinpath("data")))


def data_path(name: str) -> Path:
    """Путь к файлу данных пакета по имени."""
    path = data_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"нет файла данных {name!r} в {data_dir()}")
    return path


__all__ = ["data_dir", "data_path"]
