"""Регрессия для issue #10: у рассылки должна быть колонка bot_id, иначе /addrecurring падает."""
from bot.database.models import RecurringMessage


def test_recurring_message_has_bot_id_column():
    assert "bot_id" in RecurringMessage.__table__.columns
    assert RecurringMessage.__table__.columns["bot_id"].nullable


def test_recurring_message_accepts_bot_id():
    row = RecurringMessage(chat_id=-100, text="hi", cron_expression="0 9 * * *", bot_id=111)
    assert row.bot_id == 111
