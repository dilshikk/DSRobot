"""issue #14: Anti-NSFW на NudeNet. Модель подменяется; последний тест гоняет настоящую модель."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from aiogram.types import Animation, Chat, Document, Message, PhotoSize, Sticker, User

from bot.handlers.moderation import anti_nsfw
from bot.middlewares.moderation_pipeline import MESSAGE_CHECKS
from bot.services import nsfw

ON = {"anti_nsfw": {"enabled": True, "threshold": 60, "action": "delete"}}


def _photo(uid="p1", size=1000):
    return PhotoSize(file_id=f"id-{uid}", file_unique_id=uid, width=10, height=10, file_size=size)


def _sticker(animated=False, video=False, thumbnail=None):
    return Sticker.model_construct(
        file_id="st", file_unique_id="st", type="regular", width=512, height=512,
        is_animated=animated, is_video=video, thumbnail=thumbnail, file_size=100,
    )


class FakeBot:
    def __init__(self):
        self.downloads = []

    async def download(self, file_id, destination=None, timeout=30):
        self.downloads.append(file_id)
        destination.write(b"image-bytes")
        return destination


def _msg(bot=None, sender_chat=None, **content):
    message = Message.model_construct(
        message_id=1, date=datetime.now(), chat=Chat.model_construct(id=-100, type="supergroup"),
        from_user=User.model_construct(id=42, is_bot=False, first_name="T"), sender_chat=sender_chat,
        **content,
    )
    return message.as_(bot or FakeBot())


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(score=0.9, scored=0, deleted=[], sanctions=[], bot=FakeBot())

    async def fake_score(data):
        state.scored += 1
        return state.score

    async def fake_delete(message, notify=True):
        state.deleted.append(message.message_id)
        return True

    async def fake_sanction(bot, chat_id, user_id, action, reason="", actor_user_id=0,
                            duration_minutes=None, lang="ru"):
        state.sanctions.append((user_id, action, duration_minutes))
        return None

    monkeypatch.setattr(nsfw, "score_image", fake_score)
    monkeypatch.setattr(nsfw, "available", lambda: True)
    monkeypatch.setattr(anti_nsfw, "delete_message_safely", fake_delete)
    monkeypatch.setattr(anti_nsfw, "apply_sanction", fake_sanction)
    return state


def _check(message, settings=ON, role="member"):
    return asyncio.run(anti_nsfw.check_nsfw(message, settings, role))


def _settings(**cfg):
    return {"anti_nsfw": {**ON["anti_nsfw"], **cfg}}


# --- какую картинку проверять ---

def test_media_selection():
    thumb = _photo("thumb")
    big = _photo("big")
    assert anti_nsfw.nsfw_media(_msg(photo=[_photo("small"), big])) is big
    static = _sticker()
    assert anti_nsfw.nsfw_media(_msg(sticker=static)) is static
    assert anti_nsfw.nsfw_media(_msg(sticker=_sticker(animated=True, thumbnail=thumb))) is thumb
    assert anti_nsfw.nsfw_media(_msg(sticker=_sticker(video=True))) is None
    gif = Animation.model_construct(file_id="a", file_unique_id="a", width=1, height=1, duration=1,
                                    thumbnail=thumb)
    assert anti_nsfw.nsfw_media(_msg(animation=gif, document=Document.model_construct(
        file_id="a", file_unique_id="a", mime_type="video/mp4"))) is thumb
    image_doc = Document.model_construct(file_id="d", file_unique_id="d", mime_type="image/png")
    assert anti_nsfw.nsfw_media(_msg(document=image_doc)) is image_doc
    gif_doc = Document.model_construct(file_id="g", file_unique_id="g", mime_type="image/gif", thumbnail=None)
    assert anti_nsfw.nsfw_media(_msg(document=gif_doc)) is None
    assert anti_nsfw.nsfw_media(_msg(text="hi")) is None


def test_unsafe_score_ignores_harmless_classes():
    detections = [
        {"class": "FACE_FEMALE", "score": 0.99},
        {"class": "MALE_BREAST_EXPOSED", "score": 0.95},
        {"class": "BELLY_EXPOSED", "score": 0.9},
        {"class": "FEMALE_BREAST_EXPOSED", "score": 0.7},
        {"class": "BUTTOCKS_EXPOSED", "score": 0.4},
    ]
    assert nsfw.unsafe_score(detections) == pytest.approx(0.7)
    assert nsfw.unsafe_score(detections[:3]) == 0.0
    assert nsfw.unsafe_score([]) == 0.0


# --- проверка сообщений ---

def test_indecent_photo_is_deleted(env):
    assert _check(_msg(env.bot, photo=[_photo()])) is True
    assert env.deleted == [1]
    assert env.sanctions == []


@pytest.mark.parametrize("score, threshold, deleted", [
    (0.59, 60, False), (0.6, 60, True), (0.9, 95, False), (0.35, 30, True),
])
def test_threshold(env, score, threshold, deleted):
    env.score = score
    assert _check(_msg(env.bot, photo=[_photo()]), _settings(threshold=threshold)) is deleted


def test_score_is_cached_by_file_unique_id(env):
    for _ in range(3):
        _check(_msg(env.bot, photo=[_photo("same")]))
    assert env.scored == 1
    assert env.bot.downloads == ["id-same"]
    assert len(env.deleted) == 3


def test_large_file_is_not_downloaded(env):
    assert _check(_msg(env.bot, photo=[_photo(size=nsfw.MAX_IMAGE_BYTES + 1)])) is False
    assert env.bot.downloads == []


def test_model_unavailable_lets_messages_through(env, monkeypatch):
    monkeypatch.setattr(nsfw, "available", lambda: False)
    assert _check(_msg(env.bot, photo=[_photo()])) is False
    assert env.bot.downloads == [] and env.deleted == []


def test_model_failure_is_not_cached(env):
    env.score = None
    assert _check(_msg(env.bot, photo=[_photo()])) is False
    assert _check(_msg(env.bot, photo=[_photo()])) is False
    assert env.scored == 2


@pytest.mark.parametrize("settings, role", [
    ({"anti_nsfw": {"enabled": False}}, "member"),
    ({}, "member"),
    (ON, "admin"),
])
def test_skipped_when_off_or_for_admins(env, settings, role):
    assert _check(_msg(env.bot, photo=[_photo()]), settings, role) is False
    assert env.scored == 0


@pytest.mark.parametrize("cfg, sanction", [
    ({"action": "mute", "mute_minutes": 15}, (42, "mute", 15)),
    ({"action": "mute"}, (42, "mute", 60)),
    ({"action": "ban"}, (42, "ban", None)),
    ({"action": "warn"}, (42, "warn", None)),
])
def test_actions(env, cfg, sanction):
    assert _check(_msg(env.bot, photo=[_photo()]), _settings(**cfg)) is True
    assert env.sanctions == [sanction]


def test_channel_post_is_deleted_without_sanction(env):
    channel = Chat.model_construct(id=-200, type="channel")
    assert _check(_msg(env.bot, sender_chat=channel, photo=[_photo()]), _settings(action="ban")) is True
    assert env.deleted == [1] and env.sanctions == []


def test_check_is_wired_into_pipeline():
    assert anti_nsfw.check_nsfw in MESSAGE_CHECKS


# --- команды ---

@pytest.fixture
def saved(monkeypatch):
    calls = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def update_settings(session, chat_id, section, values):
        calls.append((section, values))

    monkeypatch.setattr(anti_nsfw, "SessionFactory", FakeSession)
    monkeypatch.setattr(anti_nsfw, "update_settings", update_settings)
    return calls


def _answers():
    answers = []

    async def answer(text, **kwargs):
        answers.append(text)

    return answers, SimpleNamespace(chat=SimpleNamespace(id=-100), answer=answer)


@pytest.mark.parametrize("args, values", [
    ("mute 10", {"action": "mute", "mute_minutes": 10}), ("ban", {"action": "ban"}),
    ("delete", {"action": "delete"}), ("off", None), ("ban 5", None), (None, None),
])
def test_nsfwaction_command(saved, args, values):
    answers, message = _answers()
    asyncio.run(anti_nsfw.set_nsfw_action(message, SimpleNamespace(args=args), lang="en"))
    assert saved == ([] if values is None else [("anti_nsfw", values)])
    assert len(answers) == 1


@pytest.mark.parametrize("args, level", [("70", 70), ("30", 30), ("95", 95), ("29", None), ("96", None), ("x", None)])
def test_nsfwlevel_command(saved, args, level):
    answers, message = _answers()
    settings = {"anti_nsfw": {"threshold": 80}}
    asyncio.run(anti_nsfw.set_nsfw_level(message, SimpleNamespace(args=args), settings, lang="en"))
    assert saved == ([] if level is None else [("anti_nsfw", {"threshold": level})])
    if level is None:
        assert "80%" in answers[0]


def test_toggle_reports_missing_model(saved, monkeypatch):
    monkeypatch.setattr(nsfw, "available", lambda: False)
    answers, message = _answers()
    asyncio.run(anti_nsfw.toggle_nsfw(message, {"anti_nsfw": {"enabled": False}}, lang="en"))
    assert saved == [("anti_nsfw", {"enabled": True})]
    assert "NSFW_ENABLED" in answers[0]


# --- настоящая модель (пакет nudenet ставится из requirements.txt) ---

def test_real_model_scores_plain_image():
    pytest.importorskip("nudenet")
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ok, encoded = cv2.imencode(".jpg", np.full((128, 128, 3), 255, dtype=np.uint8))
    assert ok
    score = asyncio.run(nsfw.score_image(encoded.tobytes()))
    assert score is not None and 0.0 <= score < 0.3
    # Не картинка: модель не падает, сообщение просто пропускается.
    assert asyncio.run(nsfw.score_image(b"not an image")) is None
