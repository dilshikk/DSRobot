"""
Anti-NSFW: локальная модель NudeNet (issue #14). Ключи и внешние сервисы не нужны:
модель 320n входит в пакет nudenet и работает на CPU через onnxruntime.

score_image() возвращает уверенность модели (0..1), что на картинке обнажённые
интимные части тела, или None, если модель недоступна или картинку не удалось разобрать.
Модель загружается при первой картинке. Распознавание идёт в отдельном потоке и по одной
картинке за раз, чтобы не блокировать обработку сообщений и не перегружать CPU.

Оценка кэшируется в Redis по file_unique_id: картинку, которую пересылают по чатам,
модель смотрит один раз. Сервер может выключить модель целиком: NSFW_ENABLED=false.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
from typing import Any

from aiogram import Bot
from aiogram.types import Document, PhotoSize, Sticker

from bot.config import settings
from bot.services.cache import redis

logger = logging.getLogger(__name__)

# Классы NudeNet 3.x, которые считаются непристойными.
# Открытые живот, ступни, подмышки и мужская грудь — нет.
UNSAFE_CLASSES = frozenset({
    "FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED", "ANUS_EXPOSED",
})
NSFW_CACHE_TTL = 7 * 24 * 3600
MAX_IMAGE_BYTES = 10 * 1024 * 1024
DOWNLOAD_TIMEOUT_SEC = 20

Media = PhotoSize | Sticker | Document

_detector: Any = None
_load_failed = False
_semaphore = asyncio.Semaphore(1)


def available() -> bool:
    """Модель включена на сервере, пакет установлен и загрузка не падала."""
    return settings.nsfw_enabled and not _load_failed and importlib.util.find_spec("nudenet") is not None


def unsafe_score(detections: list[dict]) -> float:
    """Максимальная уверенность среди непристойных классов, 0.0 если таких нет."""
    return max(
        (float(d.get("score") or 0) for d in detections if d.get("class") in UNSAFE_CLASSES),
        default=0.0,
    )


def _load_detector() -> Any:
    from nudenet import NudeDetector
    return NudeDetector()


def _detect(detector: Any, data: bytes) -> list[dict]:
    # cv2 и numpy ставятся вместе с nudenet; импорт здесь, чтобы бот запускался и без них.
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("unsupported image format")
    return detector.detect(image)


async def score_image(data: bytes) -> float | None:
    global _detector, _load_failed
    if not available():
        return None
    async with _semaphore:
        if _detector is None:
            try:
                _detector = await asyncio.to_thread(_load_detector)
            except Exception:
                _load_failed = True
                logger.exception("Cannot load NudeNet model, Anti-NSFW is disabled")
                return None
        try:
            detections = await asyncio.to_thread(_detect, _detector, data)
        except Exception as exc:
            logger.warning("NudeNet failed on image: %s", exc)
            return None
    return unsafe_score(detections)


def nsfw_cache_key(file_unique_id: str) -> str:
    return f"nsfw:{file_unique_id}"


async def media_score(bot: Bot, media: Media) -> float | None:
    """Скачивает картинку из Telegram и оценивает её. None — оценить не удалось."""
    key = nsfw_cache_key(media.file_unique_id)
    cached = await redis.get(key)
    if cached is not None:
        try:
            return float(cached)
        except ValueError:
            await redis.delete(key)

    if not available() or (media.file_size or 0) > MAX_IMAGE_BYTES:
        return None
    buffer = io.BytesIO()
    try:
        await bot.download(media.file_id, destination=buffer, timeout=DOWNLOAD_TIMEOUT_SEC)
    except Exception as exc:
        logger.warning("Cannot download %s for NSFW check: %s", media.file_unique_id, exc)
        return None

    score = await score_image(buffer.getvalue())
    if score is not None:
        await redis.set(key, f"{score:.4f}", ex=NSFW_CACHE_TTL)
    return score
