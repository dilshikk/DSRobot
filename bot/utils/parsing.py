"""Разбор числовых аргументов команд без ValueError/OverflowError (issue #45)."""
import re

_INT_RE = re.compile(r"[+-]?\d{1,20}")
CHAT_ID_LIMIT = 10 ** 15


def parse_int(raw: str | None, lo: int, hi: int) -> int | None:
    """"+5" -> 5; "--5", "5a", "", числа вне [lo, hi] -> None."""
    raw = (raw or "").strip()
    if not _INT_RE.fullmatch(raw):
        return None
    value = int(raw)
    return value if lo <= value <= hi else None


def parse_chat_id(raw: str | None) -> int | None:
    return parse_int(raw, -CHAT_ID_LIMIT, CHAT_ID_LIMIT)
