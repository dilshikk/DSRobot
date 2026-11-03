"""Подстановка в тексты админа (приветствие, прощание).

issue #50: раньше использовался str.format(), и любые другие фигурные скобки
(`{name}`, `{}`, `Правила: {см. закреп}`) давали KeyError/IndexError/ValueError — приветствие
молча не отправлялось. Теперь заменяется только известный плейсхолдер, остальное
остаётся как есть.
"""
from __future__ import annotations

MENTION_PLACEHOLDER = "{mention}"


def render_member_text(template: str, mention: str) -> str:
    return template.replace(MENTION_PLACEHOLDER, mention)
