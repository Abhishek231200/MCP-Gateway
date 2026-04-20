"""Thin Redis cache helpers used by the registry service."""

import json
from typing import Any

import redis.asyncio as aioredis

from mcp_gateway.config import settings


async def cache_get(key: str) -> Any | None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw is not None else None
    finally:
        await r.aclose()


async def cache_set(key: str, value: Any, ttl: int = 60) -> None:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.setex(key, ttl, json.dumps(value, default=str))
    finally:
        await r.aclose()


async def cache_invalidate(*keys: str) -> None:
    if not keys:
        return
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete(*keys)
    finally:
        await r.aclose()


async def cache_invalidate_prefix(*prefixes: str) -> None:
    """Delete all keys that start with any of the given prefixes (via SCAN)."""
    if not prefixes:
        return
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        to_delete: list[str] = []
        for prefix in prefixes:
            async for key in r.scan_iter(f"{prefix}*"):
                to_delete.append(key)
        if to_delete:
            await r.delete(*to_delete)
    finally:
        await r.aclose()
