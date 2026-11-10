"""Shared Telegram clients for child bots.

Creating a ``telegram.Bot`` per update costs an extra ``getMe`` round trip and a new HTTP
connection every time. Here one initialized client per bot token is kept and reused.
"""
import asyncio
from collections import OrderedDict

from telegram import Bot
from telegram.request import HTTPXRequest

from core.logger import get_logger

logger = get_logger("telegram_client")

MAX_CLIENTS = 256

_clients: "OrderedDict[str, Bot]" = OrderedDict()
_lock = asyncio.Lock()


def _new_bot(token: str) -> Bot:
    # The default pool has a single connection: concurrent updates would queue and time out.
    request = HTTPXRequest(
        connection_pool_size=8,
        pool_timeout=10.0,
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=30.0,  # uploads
    )
    return Bot(token, request=request)


async def get_client(token: str) -> Bot:
    """Return an initialized Bot for ``token`` (created on first use)."""
    async with _lock:
        client = _clients.get(token)
        if client is not None:
            _clients.move_to_end(token)
            return client
        client = _new_bot(token)
        await client.initialize()
        _clients[token] = client
        evicted = []
        while len(_clients) > MAX_CLIENTS:
            _, old = _clients.popitem(last=False)
            evicted.append(old)

    for old in evicted:
        try:
            await old.shutdown()
        except Exception:  # best effort
            logger.warning("Could not shut down an evicted Telegram client")
    return client


async def drop_client(token: str) -> None:
    """Forget a client (e.g. the token was revoked or the bot was removed)."""
    async with _lock:
        client = _clients.pop(token, None)
    if client is not None:
        try:
            await client.shutdown()
        except Exception:
            pass


async def close_all_clients() -> None:
    async with _lock:
        clients = list(_clients.values())
        _clients.clear()
    for client in clients:
        try:
            await client.shutdown()
        except Exception:
            pass
