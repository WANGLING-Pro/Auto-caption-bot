"""
utils/state.py
---------------
Minimal in-memory "what is this admin currently doing" tracker.

Pyrogram has no built-in FSM, and pulling in a full framework is overkill
for a handful of "wait for the admin's next text message" flows (setting a
template, header, footer, watermark, add/remove a word). This module is a
plain dict keyed by user_id.

NOTE: This state is process-local and non-persistent. If you run multiple
bot workers behind a load balancer, replace this with a Redis-backed store
keyed the same way. For a single-process deployment (the common case for
this kind of bot) this is sufficient.
"""

from typing import Any

_pending: dict[int, dict[str, Any]] = {}


def set_pending(user_id: int, action: str, **data):
    _pending[user_id] = {"action": action, **data}


def get_pending(user_id: int) -> dict | None:
    return _pending.get(user_id)


def clear_pending(user_id: int):
    _pending.pop(user_id, None)
