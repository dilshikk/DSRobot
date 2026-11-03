"""
Простой i18n-загрузчик JSON-локалей (bot/locales/*.json).

Язык чата хранится в Chat.lang (/setlang) и прокидывается ChatContextMiddleware в
handler data как `lang` (issue #12). Хендлеры получают его аргументом `lang: str`
и передают в t(). В личке используется язык Telegram-клиента пользователя.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
AVAILABLE_LANGS = ("ru", "en")
FALLBACK_LANG = "en"


def normalize_lang(raw: str | None, default: str = "ru") -> str:
    """'en-US' -> 'en'. Неизвестный или пустой язык -> default."""
    code = (raw or "").split("-")[0].split("_")[0].strip().lower()
    return code if code in AVAILABLE_LANGS else default


@lru_cache
def _load(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / f"{FALLBACK_LANG}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def t(lang: str, key: str, **kwargs: object) -> str:
    text = _load(lang).get(key) or _load(FALLBACK_LANG).get(key) or key
    return text.format(**kwargs) if kwargs else text


def toggle_text(lang: str, feature_key: str, enabled: bool) -> str:
    """«<Функция>: вкл./выкл.» для команд-переключателей (/antispam, /approvemode и т.д.).
    Сокращения «вкл./выкл.» не зависят от рода, поэтому одна строка подходит для всех функций."""
    state = t(lang, "state_on" if enabled else "state_off")
    return t(lang, "feature_state", feature=t(lang, feature_key), state=state)
