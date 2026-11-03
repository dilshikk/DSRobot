"""
Нормализация текста и поиск запрещённых слов (issue #8).

Текст и слова из чёрного списка приводятся к одному «скелету»:
- нижний регистр, «ё» -> «е», удаление невидимых символов;
- латинские буквы-двойники и похожие цифры -> кириллица («р0рн» и «pоpн» -> «рорн»);
- серии одинаковых букв схлопываются в одну («хееер» -> «хер»).

Одинаковое преобразование обеих сторон делает сравнение устойчивым к подменам,
а поиск по границам слов убирает ложные срабатывания («ass» больше не находится в «class»).

find_word (issue #51) — поиск ключевых слов magic-триггеров по границам слов с мягкой
нормализацией (регистр, «ё», невидимые символы, лишние пробелы).
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


def _light(text: str) -> str:
    """Мягкая нормализация для ключевых слов (issue #51): без гомоглифов и схлопывания букв,
    иначе magic-триггер «good» срабатывал бы на «god»."""
    return " ".join(text.lower().translate(_INVISIBLE).replace("ё", "е").split())


@lru_cache(maxsize=512)
def _compile_words(words: tuple[str, ...]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    variants: dict[str, str] = {}
    for word in words:
        key = _light(word)
        if key:
            variants.setdefault(key, word)
    if not variants:
        return None, {}
    # Пробел в ключевой фразе совпадает с любым количеством пробелов в тексте.
    alternation = "|".join(
        re.escape(v).replace(r"\ ", r"\s+") for v in sorted(variants, key=len, reverse=True)
    )
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)"), variants


def find_word(text: str, words: list[str] | tuple[str, ...]) -> str | None:
    """Первое слово/фраза из words, встреченное в text целиком. Возвращает исходное значение
    из words или None. Используется magic-триггерами: «hi» не находится в «this»."""
    if not text or not words:
        return None
    pattern, variants = _compile_words(tuple(sorted(words)))
    if pattern is None:
        return None
    match = pattern.search(text.lower().translate(_INVISIBLE).replace("ё", "е"))
    return variants.get(_light(match.group(0))) if match else None
