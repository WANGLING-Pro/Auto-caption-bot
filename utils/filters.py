"""
utils/filters.py
-----------------
Custom Pyrogram filters shared across plugins.
"""

from pyrogram import filters
from config import Config


def _is_admin(_, __, message):
    user = message.from_user
    return bool(user and user.id in Config.ADMINS)


admin_only = filters.create(_is_admin)
