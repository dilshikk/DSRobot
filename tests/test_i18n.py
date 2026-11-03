"""Тесты для issue #12: язык чата реально влияет на ответы, локали согласованы."""
import json
import string

import pytest

from bot.database.models import ChatSettings
from bot.handlers.welcome.goodbye import goodbye_text
from bot.handlers.welcome.welcome import welcome_text
from bot.utils.i18n import AVAILABLE_LANGS, LOCALES_DIR, normalize_lang, t
from bot.utils.telegram import rights_notice_text


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


# --- часть 2: приветствие, прощание, капча, уведомления о правах ---

def test_default_welcome_and_goodbye_follow_chat_language():
    # В DEFAULTS не должно быть зашитого русского текста, иначе он перебьёт локаль.
    defaults = ChatSettings.DEFAULTS
    assert welcome_text(defaults["welcome"], "en", "@bob") == "Welcome, @bob!"
    assert goodbye_text(defaults["goodbye"], "en", "@bob") == "@bob left the chat."
    assert welcome_text(defaults["welcome"], "ru", "@bob") == "Добро пожаловать, @bob!"


def test_custom_welcome_text_is_kept_as_is():
    cfg = {"text": "Hola, {mention}!"}
    assert welcome_text(cfg, "en", "@bob") == "Hola, @bob!"
    assert goodbye_text(cfg, "ru", "@bob") == "Hola, @bob!"


def test_usage_hints_show_literal_mention_placeholder():
    # {{mention}} в локали должен превратиться в {mention}, а не сломать format().
    assert "{mention}" in t("en", "welcome_usage")
    assert "{mention}" in t("ru", "goodbye_usage")


def test_captcha_prompt_is_translated():
    text = t("en", "captcha_prompt", mention="@bob", question="2 + 3 = ?", timeout=120)
    assert "@bob" in text and "2 + 3 = ?" in text and "120" in text
    assert "нажмите" not in text


def test_rights_notice_is_translated():
    assert "delete messages" in rights_notice_text("en", "rights_action_delete")
    assert "удалять сообщения" in rights_notice_text("ru", "rights_action_delete")
