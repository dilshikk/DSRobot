"""issue #46: проверка целевого чата при привязке и лимиты /report."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest

from bot.services import chat_binding as cb

CHAT = -100
TARGET = -200
USER = 7
BOT_ID = 42


def _message(chat_id=CHAT, user_id=USER, sender_chat=None):
    user = SimpleNamespace(id=user_id) if user_id else None
    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), from_user=user, sender_chat=sender_chat)


class FakeBot:
    id = BOT_ID

    def __init__(self, user_status="administrator", bot_member=None, chat_type="channel", fail=False):
        self.user_status = user_status
        self.bot_member = bot_member or SimpleNamespace(status="administrator", can_post_messages=True)
        self.chat_type = chat_type
        self.fail = fail

    async def get_chat(self, chat_id):
        if self.fail:
            raise TelegramBadRequest(method=None, message="chat not found")
        return SimpleNamespace(id=chat_id, type=self.chat_type)

    async def get_chat_member(self, chat_id, user_id):
        if user_id == BOT_ID:
            return self.bot_member
        return SimpleNamespace(status=self.user_status)


def _verify(bot, message=None, target=TARGET, **kwargs):
    return asyncio.run(cb.verify_target(bot, message or _message(), target, **kwargs))


def test_admin_of_target_with_posting_bot_is_allowed():
    assert _verify(FakeBot()) is None
    assert _verify(FakeBot(user_status="creator")) is None


@pytest.mark.parametrize("status", ["member", "left", "kicked", "restricted"])
def test_non_admin_of_target_is_rejected(status):
    assert _verify(FakeBot(user_status=status)) == cb.CALLER_NOT_ADMIN


def test_unreachable_target_is_rejected():
    assert _verify(FakeBot(fail=True)) == cb.TARGET_UNREACHABLE


def test_same_chat_and_anonymous_caller_are_rejected():
    assert _verify(FakeBot(), target=CHAT) == cb.SAME_CHAT
    anonymous = _message(sender_chat=SimpleNamespace(id=CHAT))
    assert _verify(FakeBot(), anonymous) == cb.ANONYMOUS_CALLER


def test_channel_requires_post_right():
    bot_member = SimpleNamespace(status="administrator", can_post_messages=False)
    assert _verify(FakeBot(bot_member=bot_member)) == cb.BOT_CANNOT_POST
    assert _verify(FakeBot(bot_member=SimpleNamespace(status="member"))) == cb.BOT_CANNOT_POST


def test_group_member_bot_can_post_but_not_moderate():
    bot = FakeBot(chat_type="supergroup", bot_member=SimpleNamespace(status="member"))
    assert _verify(bot) is None
    assert _verify(bot, bot_must_be_admin=True) == cb.BOT_NOT_ADMIN
    gone = FakeBot(chat_type="supergroup", bot_member=SimpleNamespace(status="left"))
    assert _verify(gone) == cb.BOT_CANNOT_POST


def _reserve(reporter=USER, message_id=1, chat=CHAT, privileged=False):
    return asyncio.run(cb.reserve_report(chat, reporter, message_id, privileged=privileged))


def test_same_message_is_reported_once():
    assert _reserve(reporter=1) is None
    assert _reserve(reporter=2) == cb.REPORT_DUPLICATE
    assert _reserve(reporter=3, privileged=True) == cb.REPORT_DUPLICATE


def test_user_cooldown():
    assert _reserve(message_id=1) is None
    assert _reserve(message_id=2) == cb.REPORT_USER_COOLDOWN_TEXT
    assert _reserve(message_id=3, chat=-300) is None  # кулдаун на пользователя — в пределах чата


def test_chat_limit():
    for i in range(cb.REPORT_CHAT_LIMIT):
        assert _reserve(reporter=i + 1, message_id=i + 1) is None
    assert _reserve(reporter=999, message_id=999) == cb.REPORT_CHAT_LIMIT_TEXT


def test_privileged_skip_cooldown():
    assert _reserve(message_id=1, privileged=True) is None
    assert _reserve(message_id=2, privileged=True) is None


def test_released_report_can_be_retried():
    assert _reserve(reporter=1) is None
    asyncio.run(cb.release_report(CHAT, 1))
    assert _reserve(reporter=2) is None
