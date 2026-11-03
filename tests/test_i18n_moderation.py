"""Тесты для issue #12, часть 4: переключатели, блокировки, роли — на языке чата."""
import pytest

from bot.handlers.moderation.anti_nsfw import nsfw_toggle_text
from bot.handlers.moderation.blocks import TOGGLES
from bot.handlers.moderation.custom_roles import role_created_text
from bot.utils.i18n import t, toggle_text

FEATURES = [
    "feature_approve_mode", "feature_anti_nsfw", "feature_antispam",
    "feature_masked_links", "feature_clean_service",
]


@pytest.mark.parametrize("feature", FEATURES)
def test_every_toggle_feature_has_a_translation(feature):
    # Ключ, которого нет в локали, вернулся бы как есть и попал бы в чат.
    assert t("ru", feature) != feature
    assert t("en", feature) != feature


def test_toggle_text_follows_chat_language():
    assert toggle_text("en", "feature_antispam", True) == "Antispam: on"
    assert toggle_text("en", "feature_antispam", False) == "Antispam: off"
    assert toggle_text("ru", "feature_antispam", True) == "Антиспам: вкл."


def test_nsfw_warning_only_when_enabled():
    assert ".env" in nsfw_toggle_text("en", True)
    assert ".env" not in nsfw_toggle_text("en", False)


def test_block_usage_lists_options_in_stable_order():
    text = t("en", "block_usage", options=" | ".join(TOGGLES))
    assert text == "Usage: /block forwards | links | usernames | bots | inline"
    # Без угловых скобок: бот шлёт сообщения с parse_mode=HTML, и "<a|b>" ломал разметку.
    assert "<" not in text


def test_role_name_is_html_escaped():
    text = role_created_text("en", "<b>mod", ["ban"])
    assert "&lt;b&gt;mod" in text and "<b>" not in text
    assert text.endswith(": ban")
    assert role_created_text("ru", "mod", []).endswith(": \u2014")


def test_kick_bots_rights_action_is_translated():
    assert t("en", "rights_action_kick_bots") == "remove added bots"
    assert t("ru", "rights_action_kick_bots") == "удалять добавленных ботов"
