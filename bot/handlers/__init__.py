"""
Регистрация всех роутеров бота. Каждый модуль из ТЗ — отдельный файл-роутер,
что соответствует Router/Dispatcher слою из архитектуры (см. README).
"""
from aiogram import Dispatcher

from bot.handlers.core import clones, lang_settings, start_help, time_settings
from bot.handlers.moderation import (
    anonymous_admins, antiflood, antispam, anti_nsfw, approve_mode, banned_words,
    blocks, channel_moderation, custom_roles, link_settings, masked_users,
    max_message_length, media_blocks, message_deletion, moderation_commands,
    night_mode, roles_permissions, warns,
)
from bot.handlers.welcome import captcha, goodbye, rules, welcome
from bot.handlers.chat import (
    admin_tag, checks_settings, discussion_group, group_statistics, log_channel,
    magic_stickers_gifs, members_management, permissions_editor, personal_commands,
    privacy, recurring_messages, staff_group, tag_settings, topics_settings,
)
from bot.handlers.misc import alphabets, crypto_prices

ALL_ROUTERS = [
    # core
    start_help.router, clones.router, time_settings.router, lang_settings.router,
    # moderation
    roles_permissions.router, custom_roles.router, moderation_commands.router,
    channel_moderation.router, anonymous_admins.router, warns.router,
    antiflood.router, antispam.router, blocks.router, media_blocks.router,
    anti_nsfw.router, banned_words.router, link_settings.router, approve_mode.router,
    message_deletion.router, night_mode.router, max_message_length.router, masked_users.router,
    # welcome
    welcome.router, goodbye.router, rules.router, captcha.router,
    # chat
    checks_settings.router, admin_tag.router, tag_settings.router, topics_settings.router,
    recurring_messages.router, members_management.router, discussion_group.router,
    personal_commands.router, magic_stickers_gifs.router, log_channel.router,
    staff_group.router, group_statistics.router, permissions_editor.router, privacy.router,
    # misc
    alphabets.router, crypto_prices.router,
]


def register_all_routers(dp: Dispatcher) -> None:
    for router in ALL_ROUTERS:
        dp.include_router(router)
