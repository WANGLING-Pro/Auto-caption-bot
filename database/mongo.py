"""
database/mongo.py
------------------
Single shared MongoDB client using Motor (async driver for PyMongo).
All other database modules import `db` from here.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

_client = AsyncIOMotorClient(Config.MONGO_URI)
db = _client[Config.MONGO_DB_NAME]

# Collections
users_col = db["users"]
channels_col = db["channels"]
stats_col = db["stats"]
