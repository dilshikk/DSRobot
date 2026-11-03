"""Регрессионные тесты для issue #1: одно сообщение проходит через ВСЕ включённые
проверки по порядку, а не перехватывается первым хендлером."""
import asyncio
from datetime import datetime

import pytest
from aiogram.types import Chat, Message, MessageEntity, User

from bot.middlewares import moderation_pipeline as mp


def _msg(text: str | None = "hello", *, edited: bool = False, chat_type: str = "supergroup",
         command: bool = False) -> Message:
    entities = None
    if command:
        entities = [MessageEntity(type="bot_command", offset=0, length=len(text.split()[0]))]
    return Message.model_construct(
        message_id=1,
        date=datetime.now(),
        chat=Chat.model_construct(id=-100, type=chat_type),
        from_user=User.model_construct(id=42, is_bot=False, first_name="Test"),
        text=text,
        entities=entities,
        edit_date=int(datetime.now().timestamp()) if edited else None,
    )


class Recorder:
    """Фейковые проверки, которые запоминают порядок вызова."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self, name: str, result: bool = False, error: bool = False):
        async def _check(message, settings, role):
            self.calls.append(name)
            if error:
                raise RuntimeError("boom")
            return result

        _check.__name__ = name
        return _check


@pytest.fixture
def env(monkeypatch):
    rec = Recorder()
    stats: list[str] = []
    autodelete: list[int] = []

    # Сигнатура как у настоящего bump_stat (issue #47 добавил utc_offset).
    async def fake_bump(chat_id, field, utc_offset=0):
        stats.append(field)

    monkeypatch.setattr(mp, "bump_stat", fake_bump)
    monkeypatch.setattr(
        mp.message_deletion, "schedule_command_autodelete",
        lambda message, settings: autodelete.append(message.message_id),
    )
    return rec, stats, autodelete


def _run(message: Message, settings: dict | None = None):
    handled: list[Message] = []

    async def handler(event, data):
        handled.append(event)
        return "handled"

    data = {"chat_settings": {} if settings is None else settings, "chat_user_role": "member"}
    result = asyncio.run(mp.ModerationPipelineMiddleware()(handler, message, data))
    return result, handled


def test_all_checks_run_in_order_and_handler_is_called(env, monkeypatch):
    rec, stats, _ = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a"), rec.check("b"), rec.check("c")])

    result, handled = _run(_msg())

    assert rec.calls == ["a", "b", "c"]
    assert result == "handled" and len(handled) == 1
    assert stats == ["messages_count"]


def test_chain_stops_after_check_deletes_message(env, monkeypatch):
    rec, stats, _ = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a"), rec.check("b", result=True), rec.check("c")])

    result, handled = _run(_msg())

    assert rec.calls == ["a", "b"]
    assert result is None and handled == []
    assert stats == []


def test_failing_check_does_not_break_others(env, monkeypatch):
    rec, _, _ = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a", error=True), rec.check("b")])

    result, handled = _run(_msg())

    assert rec.calls == ["a", "b"]
    assert len(handled) == 1


def test_commands_pass_checks_and_reach_handlers(env, monkeypatch):
    rec, stats, autodelete = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a"), rec.check("b")])

    _, handled = _run(_msg("/stats", command=True))

    assert rec.calls == ["a", "b"]
    assert len(handled) == 1
    assert autodelete == [1]
    assert stats == []


def test_command_with_spam_is_deleted(env, monkeypatch):
    """issue #34: аргументы команды тоже проверяются."""
    rec, stats, autodelete = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("links", result=True)])

    result, handled = _run(_msg("/rules https://spam.ru", command=True))

    assert result is None and handled == []
    assert autodelete == []


def test_slash_text_without_command_entity_is_moderated(env, monkeypatch):
    """issue #34: "/ купить ..." не команда и не должна обходить фильтры."""
    rec, stats, autodelete = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("links", result=True)])

    result, handled = _run(_msg("/ купить тут https://spam.ru"))

    assert rec.calls == ["links"]
    assert result is None and handled == []
    assert autodelete == []


def test_commands_skip_alphabet_check(env, monkeypatch):
    rec, _, _ = env
    alphabet = rec.check("alphabet", result=True)
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a"), alphabet])
    monkeypatch.setattr(mp, "SKIP_ON_COMMAND", {alphabet})

    _, handled = _run(_msg("/price btc", command=True))

    assert rec.calls == ["a"]
    assert len(handled) == 1


def test_real_alphabet_check_is_skipped_for_commands():
    assert mp.alphabets.check_alphabet in mp.SKIP_ON_COMMAND


def test_edited_message_skips_antispam_and_stats(env, monkeypatch):
    rec, stats, _ = env
    spam = rec.check("antispam")
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("words"), spam])
    monkeypatch.setattr(mp, "SKIP_ON_EDIT", {spam})

    _run(_msg(edited=True))

    assert rec.calls == ["words"]
    assert stats == []


def test_private_chat_bypasses_pipeline(env, monkeypatch):
    rec, _, _ = env
    monkeypatch.setattr(mp, "MESSAGE_CHECKS", [rec.check("a", result=True)])

    _, handled = _run(_msg(chat_type="private"))

    assert rec.calls == []
    assert len(handled) == 1


def test_real_pipeline_contains_all_background_checks():
    names = [c.__name__ for c in mp.MESSAGE_CHECKS]
    for expected in ("check_banned_words", "check_links", "check_duplicate_spam", "check_media_block"):
        assert expected in names
    # antispam должен идти последним, иначе он снова «съест» сообщение раньше фильтров
    assert names[-1] == "check_duplicate_spam"


def test_throttling_runs_after_moderation():
    """issue #34: throttling не должен отбрасывать сообщение до проверок модерации."""
    from aiogram import Dispatcher

    from bot.main import setup_middlewares
    from bot.middlewares.throttling import ThrottlingMiddleware

    dp = Dispatcher()
    setup_middlewares(dp)

    assert not any(isinstance(m, ThrottlingMiddleware) for m in dp.message.outer_middleware)
    assert any(isinstance(m, ThrottlingMiddleware) for m in dp.message.middleware)
