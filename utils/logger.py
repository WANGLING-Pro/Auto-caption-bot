"""
utils/logger.py
----------------
Central logging configuration. Import `LOGGER` anywhere you need to log.

Set the env var LOG_LEVEL=DEBUG on Render to see the extra debug lines
(handler decisions, formatting mode, ...). Default is INFO.
"""

import logging
import os
import sys

_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
_level = getattr(logging, _level_name, logging.INFO)

logging.basicConfig(
    level=_level,
    format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

# Quiet down noisy third-party loggers (pyrogram still logs handler
# exceptions at ERROR level, which stays visible).
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

LOGGER = logging.getLogger("caption_bot")
