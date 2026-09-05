"""
database/users.py
------------------
CRUD helpers for the `users` collection.

Schema:
{
    "_id": <int>,          # Telegram user ID
    "first_name": <str>,
    "username": <str|None>,
    "joined_at": <datetime>,
}
"""

from datetime import datetime, timezone
from database.mongo import users_col


async def add_user_if_new(user_id: int, first_name: str, username: str | None):
    existing = await users_col.find_one({"_id": user_id})
    if existing:
        return False
    await users_col.insert_one(
        {
            "_id": user_id,
            "first_name": first_name,
            "username": username,
            "joined_at": datetime.now(timezone.utc),
        }
    )
    return True


async def get_all_user_ids() -> list[int]:
    cursor = users_col.find({}, {"_id": 1})
    return [doc["_id"] async for doc in cursor]


async def total_users() -> int:
    return await users_col.count_documents({})
