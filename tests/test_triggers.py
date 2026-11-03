"""issue #51: magic-триггеры по целым словам, кэш триггеров, заметки любого типа и /notes."""
import asyncio
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendSticker

from bot.handlers.chat import magic_stickers_gifs, personal_commands
from bot.services import triggers
from bot.services.triggers import Trigger, extract_response, find_magic, find_note
from bot.utils.text_match import find_word

NOTE = Trigger("#rules", "text", "Правила: не спамить")
PHOTO_NOTE = Trigger("#map", "photo", "photo-id")
MAGIC_HI = Trigger("hi", "sticker", "sticker-id")
MAGIC_GM = Trigger("good morning", "gif", "gif-id")
ALL = [NOTE, PHOTO_NOTE, MAGIC_HI, MAGIC_GM]


@pytest.mark.parametrize("text, found", [
    ("this is white", None),        # раньше срабатывало по подстроке
    ("Hi all!", "hi"),
    ("oh, hi.", "hi"),
    ("hi_there", None),
    ("god", None),                  # без схлопывания букв: «good» != «god»
    ("Good   morning, chat", "good morning"),
    ("при\u200bвет", "привет"),
])
def test_find_word_uses_word_boundaries(text, found):
    assert find_word(text, ["hi", "good", "good morning", "привет"]) == found


def test_find_word_prefers_longer_phrase_and_handles_empty():
    assert find_word("привет всем", ["привет", "привет всем"]) == "привет всем"
    assert find_word("", ["hi"]) is None
    assert find_word("hi", []) is None


def test_find_magic_ignores_notes_and_substrings():
    assert find_magic("white hills", ALL) is None
    assert find_magic("ну hi", ALL) is MAGIC_HI
    assert find_magic("rules", ALL) is None  # заметка не magic


def test_find_note_by_first_word():
    assert find_note("#Rules пожалуйста", ALL) is NOTE
    assert find_note("#map", ALL) is PHOTO_NOTE
    assert find_note("#unknown", ALL) is None
    assert find_note("rules", ALL) is None
    assert find_note("#hi", ALL) is None  # magic-триггер не заметка


def _reply(**fields):
    base = dict(sticker=None, animation=None, photo=None, video=None, document=None, text=None, html_text=None)
    base.update(fields)
    return SimpleNamespace(**base)


def test_extract_response_types():
    assert extract_response(_reply(sticker=SimpleNamespace(file_id="s"))) == ("sticker", "s")
    # У GIF Telegram заполняет и animation, и document.
    gif = _reply(animation=SimpleNamespace(file_id="g"), document=SimpleNamespace(file_id="d"))
    assert extract_response(gif) == ("gif", "g")
    photo = _reply(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")])
    assert extract_response(photo) == ("photo", "big")
    assert extract_response(_reply(text="a < b", html_text="a &lt; b")) == ("text", "a &lt; b")
    assert extract_response(_reply()) is None


@pytest.mark.parametrize("raw, trigger", [
    ("Rules", "#rules"), ("#Rules", "#rules"), ("#", None), ("", None), (None, None), ("x" * 200, None),
])
def test_note_trigger(raw, trigger):
    assert personal_commands.note_trigger(raw) == trigger


def test_parse_note_from_args_and_reply():
    assert personal_commands.parse_note("#rules не спамить", None) == ("#rules", "text", "не спамить")
    sticker = _reply(sticker=SimpleNamespace(file_id="s"))
    assert personal_commands.parse_note("#cat", sticker) == ("#cat", "sticker", "s")
    assert personal_commands.parse_note("#cat", None) is None
    assert personal_commands.parse_note("#cat", _reply()) is None
    assert personal_commands.parse_note(None, sticker) is None


@pytest.mark.parametrize("raw, keyword", [
    ("  Good   Morning ", "good morning"), ("#hi", None), ("", None), (None, None),
])
def test_magic_keyword(raw, keyword):
    assert magic_stickers_gifs.magic_keyword(raw) == keyword


def test_notes_list_separates_notes_and_magic():
    text = personal_commands.notes_list_text(ALL)
    assert "#map, #rules" in text and "good morning, hi" in text
    assert personal_commands.notes_list_text([]) == "Заметок пока нет."


class FakeSession:
    def __init__(self, rows):
        self.rows, self.queries = rows, 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.queries += 1
        return SimpleNamespace(all=lambda: self.rows)


@pytest.fixture
def cache(monkeypatch):
    store, sessions = {}, []

    async def get_json(key):
        return store.get(key)

    async def set_json(key, value, ex=None):
        store[key] = value

    def session_factory():
        session = FakeSession([SimpleNamespace(trigger="hi", response_type="sticker", response_content="s")])
        sessions.append(session)
        return session

    monkeypatch.setattr(triggers, "get_json", get_json)
    monkeypatch.setattr(triggers, "set_json", set_json)
    monkeypatch.setattr(triggers, "SessionFactory", session_factory)
    return store, sessions


def test_triggers_are_cached(cache):
    store, sessions = cache
    first = asyncio.run(triggers.get_triggers(-100))
    second = asyncio.run(triggers.get_triggers(-100))
    assert first == second == [Trigger("hi", "sticker", "s")]
    assert len(sessions) == 1  # второй вызов не идёт в БД
    assert "triggers:-100" in store


def test_empty_list_is_cached_too(cache, monkeypatch):
    store, _ = cache
    store["triggers:-1"] = []
    monkeypatch.setattr(triggers, "SessionFactory", lambda: pytest.fail("БД не должна вызываться"))
    assert asyncio.run(triggers.get_triggers(-1)) == []


def _text_message(text):
    return SimpleNamespace(text=text, chat=SimpleNamespace(id=-100))


def test_magic_filter_passes_unmatched_messages_on(monkeypatch):
    async def get_triggers(chat_id):
        return ALL

    monkeypatch.setattr(magic_stickers_gifs, "get_triggers", get_triggers)
    assert asyncio.run(magic_stickers_gifs.magic_match(_text_message("this is white"))) is False
    assert asyncio.run(magic_stickers_gifs.magic_match(_text_message("/start hi"))) is False
    assert asyncio.run(magic_stickers_gifs.magic_match(_text_message("hi!"))) == {"magic": MAGIC_HI}


def test_note_filter(monkeypatch):
    async def get_triggers(chat_id):
        return ALL

    monkeypatch.setattr(personal_commands, "get_triggers", get_triggers)
    assert asyncio.run(personal_commands.note_match(_text_message("#rules"))) == {"note": NOTE}
    assert asyncio.run(personal_commands.note_match(_text_message("#nope"))) is False
    assert asyncio.run(personal_commands.note_match(_text_message("rules"))) is False


@pytest.mark.parametrize("module", [personal_commands, magic_stickers_gifs])
def test_routers_are_group_only(module):
    assert module.router.message._handler.filters, f"{module.__name__}: нет фильтра типа чата"


def test_send_response_uses_matching_method_and_survives_errors():
    sent = []

    async def answer_photo(content):
        sent.append(("photo", content))

    async def answer_sticker(content):
        raise TelegramBadRequest(SendSticker(chat_id=-100, sticker=content), "Bad Request: wrong file identifier")

    message = SimpleNamespace(chat=SimpleNamespace(id=-100), answer_photo=answer_photo, answer_sticker=answer_sticker)
    asyncio.run(triggers.send_response(message, PHOTO_NOTE))
    asyncio.run(triggers.send_response(message, MAGIC_HI))  # ошибка Telegram логируется, а не падает
    asyncio.run(triggers.send_response(message, Trigger("#x", "unknown", "")))
    assert sent == [("photo", "photo-id")]
