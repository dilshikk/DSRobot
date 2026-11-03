"""Тесты для issue #12: язык чата реально влияет на ответы, локали согласованы."""
import json
import string

import pytest

from bot.utils.i18n import AVAILABLE_LANGS, LOCALES_DIR, normalize_lang, t


def _locale(lang: str) -> dict[str, str]:
    return json.loads((LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_all_locales_have_the_same_keys():
    keys = {lang: set(_locale(lang)) for lang in AVAILABLE_LANGS}
    assert keys["ru"] == keys["en"]


def test_placeholders_match_between_locales():
    ru, en = _locale("ru"), _locale("en")
    mismatched = [key for key in ru if _placeholders(ru[key]) != _placeholders(en[key])]
    assert mismatched == []


def test_chat_language_changes_the_reply():
    assert t("ru", "user_unmuted") != t("en", "user_unmuted")
    assert "Unmuted" in t("en", "user_unmuted")


def test_formatting_and_fallbacks():
    assert "@nick" in t("en", "target_username_not_found", username="nick")
    assert t("de", "user_unmuted") == t("en", "user_unmuted")  # неизвестный язык -> en
    assert t("ru", "no_such_key") == "no_such_key"


@pytest.mark.parametrize("raw, expected", [
    ("ru", "ru"), ("en", "en"), ("en-US", "en"), ("EN_gb", "en"), ("de", "ru"), (None, "ru"), ("", "ru"),
])
def test_normalize_lang(raw, expected):
    assert normalize_lang(raw) == expected
