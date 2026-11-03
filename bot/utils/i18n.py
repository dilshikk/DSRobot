"""Простейший i18n-загрузчик JSON-локалей. Langs and lang settings."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


@lru_cache
def _load(lang: str) -> dict:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def t(lang: str, key: str, **kwargs) -> str:
    data = _load(lang)
    text = data.get(key) or _load("en").get(key) or key
    return text.format(**kwargs) if kwargs else text
