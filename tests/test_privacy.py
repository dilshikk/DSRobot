"""issue #36: /forget не должен сбрасывать варны и историю санкций."""
import asyncio

from sqlalchemy.dialects import postgresql

from bot.services.privacy_service import forget_user


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, moderated_chats):
        self.moderated_chats = moderated_chats
        self.sql: list[str] = []

    async def execute(self, stmt):
        compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        self.sql.append(str(compiled))
        return FakeResult(self.moderated_chats if self.sql[-1].lstrip().startswith("SELECT") else [])


def _deletes(session):
    return [s for s in session.sql if s.startswith("DELETE")]


def _chat_user_deletes(session):
    # issue #92: /forget также удаляет user_message_stats — это проверяется в test_stats_period_top.py.
    return [s for s in _deletes(session) if s.startswith("DELETE FROM chat_users")]


def test_forget_keeps_audit_log_and_warned_chat_user():
    session = FakeSession(moderated_chats=[-100])

    kept = asyncio.run(forget_user(session, 42, -100))

    assert kept is True
    assert not any("audit_log" in s for s in _deletes(session))
    (chat_user_delete,) = _chat_user_deletes(session)
    assert "chat_users.user_id = 42" in chat_user_delete
    assert "NOT IN (-100)" in chat_user_delete


def test_forget_without_history_deletes_chat_user_and_anonymizes():
    session = FakeSession(moderated_chats=[])

    kept = asyncio.run(forget_user(session, 42, -100))

    assert kept is False
    (chat_user_delete,) = _chat_user_deletes(session)
    assert "chat_users.chat_id = -100" in chat_user_delete and "NOT IN" not in chat_user_delete
    assert any(s.startswith("UPDATE users") and "username=NULL" in s for s in session.sql)


def test_forgetme_everywhere_keeps_moderated_chats():
    session = FakeSession(moderated_chats=[-100, -200])

    assert asyncio.run(forget_user(session, 42)) is True
    (chat_user_delete,) = _chat_user_deletes(session)
    assert "chat_users.chat_id =" not in chat_user_delete
    assert "NOT IN (-100, -200)" in chat_user_delete or "NOT IN (-200, -100)" in chat_user_delete
