"""Тесты для issue #12, часть 5: настройки чата, клоны, часовой пояс, «разное» — на языке чата."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from bot.handlers.chat.checks_settings import REQUIRED_RIGHTS, missing_rights_text
from bot.handlers.chat.group_statistics import stats_text
from bot.handlers.chat.members_management import inactive_text
from bot.handlers.chat.permissions_editor import setcmdperm_usage
from bot.handlers.chat.privacy import privacy_mode_text
from bot.handlers.chat.recurring_messages import recurring_added_text
from bot.handlers.chat.staff_group import report_notice_text
from bot.handlers.core.clones import clones_list_text, with_token_warning
from bot.handlers.core.time_settings import parse_offset
from bot.handlers.misc.alphabets import parse_alphabets
from bot.handlers.misc.crypto_prices import price_text, resolve_coin
from bot.utils.i18n import t


@pytest.mark.parametrize("right", REQUIRED_RIGHTS)
def test_every_required_right_has_a_human_name(right):
    # Ключ без перевода вернулся бы как есть, и в чат снова попало бы «can_pin_messages».
    for lang in ("ru", "en"):
        assert t(lang, f"right_{right}") != f"right_{right}"


def test_missing_rights_are_translated():
    assert missing_rights_text("en", []) == "✅ The bot has all the required rights."
    text = missing_rights_text("en", ["can_pin_messages", "can_delete_messages"])
    assert text.endswith("pin messages, delete messages")
    assert "can_" not in text


def test_stats_follow_chat_language():
    row = SimpleNamespace(messages_count=5, joins_count=None, leaves_count=1, sanctions_count=0)
    text = stats_text("en", row)
    assert "Messages: 5" in text and "Joins: 0" in text
    assert stats_text("ru", None) == "Статистики за сегодня пока нет."


def test_inactive_list_is_translated():
    assert "30 days" in inactive_text("en", 30, [])
    text = inactive_text("en", 7, [("bob", datetime(2026, 1, 2))])
    assert text == "Inactive for more than 7 days (1):\n• bob — last seen 2026-01-02"


@pytest.mark.parametrize("text", [
    setcmdperm_usage("en"),
    t("en", "setutc_usage", min=-12, max="+14"),
    t("en", "addclone_usage"),
    t("en", "delclone_usage"),
    t("ru", "linkdiscussion_usage"),
    t("ru", "setlogchannel_usage"),
])
def test_usage_hints_have_no_angle_brackets(text):
    # Бот шлёт сообщения с parse_mode=HTML: «<команда>» ломал разметку, и подсказка не доходила.
    assert "<" not in text and ">" not in text


def test_setcmdperm_usage_lists_roles_without_developer():
    text = setcmdperm_usage("en")
    assert "owner" in text and "developer" not in text


def test_privacy_mode_text():
    assert privacy_mode_text("en", True).startswith("Privacy mode: on")
    assert privacy_mode_text("ru", False).startswith("Режим приватности: выкл.")


def test_recurring_added_escapes_cron():
    text = recurring_added_text("en", 3, "0 9 * * <b>", -5)
    assert "#3" in text and "&lt;b&gt;" in text and "(UTC-5)" in text
    assert "(UTC+3)" in recurring_added_text("ru", 1, "0 9 * * *", 3)


def test_report_notice_escapes_chat_title():
    text = report_notice_text("en", "@bob", "A<B")
    assert text == "🚩 Report from @bob in chat A&lt;B"
    assert report_notice_text("en", "@bob", None).endswith("in chat ")


def test_clone_texts():
    assert clones_list_text("en", []) == "You have no clones."
    clones = [SimpleNamespace(id=1, bot_username="a_bot", is_active=True),
              SimpleNamespace(id=2, bot_username="", is_active=False)]
    text = clones_list_text("en", clones)
    assert "#1 @a_bot — active" in text and "#2 @??? — disabled" in text
    assert with_token_warning("en", "ok", True) == "ok"
    assert "manually" in with_token_warning("en", "ok", False)


@pytest.mark.parametrize("raw, expected", [
    ("3", 3), ("+3", 3), ("-12", -12), ("+14", 14), (" 0 ", 0),
    ("15", None), ("-13", None), ("abc", None), ("", None), (None, None),
])
def test_parse_offset(raw, expected):
    assert parse_offset(raw) == expected


def test_parse_alphabets_is_case_insensitive_and_deduplicated():
    assert parse_alphabets("Latin, cyrillic,latin, foo") == ["latin", "cyrillic"]
    assert parse_alphabets(None) == []


def test_price_text():
    assert resolve_coin(" BTC ") == "bitcoin"
    assert price_text("en", "bitcoin", {"bitcoin": {"usd": 65000}}) == "💱 BITCOIN: $65,000"
    # Непредвиденный ответ сервиса не должен ронять хендлер.
    assert price_text("en", "x", {"x": {}}) == t("en", "price_not_found")
    assert price_text("en", "x", ["oops"]) == t("en", "price_not_found")
    assert "&lt;" in price_text("en", "<b>", {"<b>": {"usd": 1}})
