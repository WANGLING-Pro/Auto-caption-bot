"""
database/channels.py
---------------------
CRUD helpers for the `channels` collection.

Schema (one document per channel):
{
    "_id": <int>,                 # Telegram channel ID (negative, -100...)
    "owner_id": <int>,            # Telegram user ID of the admin who added it
    "title": <str>,
    "username": <str|None>,       # without @, None if private channel
    "verified_admin": <bool>,     # confirmed the bot is an admin in this channel
    "settings": {
        "auto_caption": <bool>,
        "caption_template": <str|None>,
        "header": <str|None>,
        "footer": <str|None>,
        "watermark": <str|None>,
        "replace_words": [ {"from": <str>, "to": <str>} ],
        "remove_words": [ <str> ],
    },
    "stats": {
        "edited_messages": <int>,
    },
    "created_at": <datetime>,
}
"""

from datetime import datetime, timezone
from database.mongo import channels_col

DEFAULT_SETTINGS = {
    "auto_caption": False,          # off until admin explicitly enables it
    "caption_template": None,       # None => fall back to {default_caption}
    "header": None,
    "footer": None,
    "watermark": None,
    "replace_words": [],            # [{"from": "...", "to": "..."}]
    "remove_words": [],             # ["...", "..."]
}


async def add_channel(channel_id: int, owner_id: int, title: str, username: str | None):
    """Insert a new channel, or return the existing doc if already added."""
    existing = await channels_col.find_one({"_id": channel_id})
    if existing:
        return existing

    doc = {
        "_id": channel_id,
        "owner_id": owner_id,
        "title": title,
        "username": username,
        "verified_admin": True,   # set True only after the add-flow confirms bot admin status
        "settings": dict(DEFAULT_SETTINGS),
        "stats": {"edited_messages": 0},
        "created_at": datetime.now(timezone.utc),
    }
    await channels_col.insert_one(doc)
    return doc


async def get_channel(channel_id: int):
    return await channels_col.find_one({"_id": channel_id})


async def get_user_channels(owner_id: int):
    cursor = channels_col.find({"owner_id": owner_id})
    return [c async for c in cursor]


async def delete_channel(channel_id: int):
    await channels_col.delete_one({"_id": channel_id})


async def update_settings(channel_id: int, **fields):
    """Update one or more keys inside `settings`."""
    update = {f"settings.{k}": v for k, v in fields.items()}
    await channels_col.update_one({"_id": channel_id}, {"$set": update})


async def reset_settings(channel_id: int):
    await channels_col.update_one(
        {"_id": channel_id}, {"$set": {"settings": dict(DEFAULT_SETTINGS)}}
    )


async def add_replace_word(channel_id: int, word_from: str, word_to: str):
    await channels_col.update_one(
        {"_id": channel_id},
        {"$push": {"settings.replace_words": {"from": word_from, "to": word_to}}},
    )


async def remove_replace_word(channel_id: int, word_from: str):
    await channels_col.update_one(
        {"_id": channel_id},
        {"$pull": {"settings.replace_words": {"from": word_from}}},
    )


async def add_remove_word(channel_id: int, phrase: str):
    await channels_col.update_one(
        {"_id": channel_id},
        {"$addToSet": {"settings.remove_words": phrase}},
    )


async def remove_remove_word(channel_id: int, phrase: str):
    await channels_col.update_one(
        {"_id": channel_id},
        {"$pull": {"settings.remove_words": phrase}},
    )


async def increment_edited_count(channel_id: int):
    await channels_col.update_one(
        {"_id": channel_id}, {"$inc": {"stats.edited_messages": 1}}
    )


async def total_channels() -> int:
    return await channels_col.count_documents({})


async def total_edited_messages() -> int:
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$stats.edited_messages"}}}]
    result = await channels_col.aggregate(pipeline).to_list(length=1)
    return result[0]["total"] if result else 0
