"""
Нормализация текста и поиск запрещённых слов (issue #8).

Текст и слова из чёрного списка приводятся к одному «скелету»:
- нижний регистр, «ё» -> «е», удаление невидимых символов;
- латинские буквы-двойники и похожие цифры -> кириллица («р0рн» и «pоpн» -> «рорн»);
- серии одинаковых букв схлопываются в одну («хееер» -> «хер»).

Одинаковое преобразование обеих сторон делает сравнение устойчивым к подменам,
а поиск по границам слов убирает ложные срабатывания («ass» больше не находится в «class»).
"""
from __future__ import annotations

import re
from functools import lru_cache

MATCH_WORD = "word"
MATCH_SUBSTRING = "substring"
MATCH_MODES = (MATCH_WORD, MATCH_SUBSTRING)

_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)

_HOMOGLYPHS = str.maketrans({
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к", "m": "м",
    "o": "о", "p": "р", "t": "т", "x": "х", "y": "у", "ё": "е",
    "0": "о", "3": "з", "4": "ч", "6": "б",
})

_REPEATS = re.compile(r"(.)\1+", re.DOTALL)


def normalize(text: str) -> str:
    text = text.lower().translate(_INVISIBLE).translate(_HOMOGLYPHS)
    return _REPEATS.sub(r"\1", text)


@lru_cache(maxsize=512)
def _compile(words: tuple[str, ...], mode: str) -> re.Pattern[str] | None:
    variants = sorted({normalize(w) for w in words if w.strip()}, key=len, reverse=True)
    if not variants:
        return None
    alternation = "|".join(re.escape(v) for v in variants)
    if mode == MATCH_SUBSTRING:
        return re.compile(alternation)
    # (?<!\w)/(?!\w) вместо \b: корректно работает и для слов, которые начинаются
    # или заканчиваются не буквой.
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)")


def find_banned(text: str, words: list[str] | tuple[str, ...], mode: str = MATCH_WORD) -> bool:
    if not text or not words:
        return False
    pattern = _compile(tuple(sorted(words)), mode if mode in MATCH_MODES else MATCH_WORD)
    return bool(pattern and pattern.search(normalize(text)))
