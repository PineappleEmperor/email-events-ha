"""Persistent storage for user-defined schemas and per-sender extraction stats."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONFIDENCE_LOW,
    SCHEMA_STORAGE_KEY,
    SCHEMA_STORAGE_VERSION,
    STATS_STORAGE_KEY,
    STATS_STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _empty_stat() -> dict[str, Any]:
    return {
        "total_processed": 0,
        "total_matched": 0,
        "confidence_high": 0,
        "confidence_medium": 0,
        "confidence_low": 0,
        "last_matched_at": None,
    }


class SchemaStore:
    """User-defined schemas stored in .storage/email_events_ha.schemas."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the schema store."""
        self._store: Store[dict[str, Any]] = Store(hass, SCHEMA_STORAGE_VERSION, SCHEMA_STORAGE_KEY)
        self._schemas: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load schemas from storage."""
        data = await self._store.async_load()
        self._schemas = (data or {}).get("schemas", {})

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return a copy of all user-defined schemas."""
        return dict(self._schemas)

    def get(self, schema_id: str) -> dict[str, Any] | None:
        """Return a single user schema by ID, or None."""
        return self._schemas.get(schema_id)

    async def async_save_schema(self, schema_id: str, schema_def: dict[str, Any]) -> None:
        """Create or replace a user schema and persist to disk."""
        self._schemas[schema_id] = schema_def
        await self._store.async_save({"schemas": self._schemas})

    async def async_delete_schema(self, schema_id: str) -> bool:
        """Delete a user schema; returns True if it existed."""
        if schema_id not in self._schemas:
            return False
        del self._schemas[schema_id]
        await self._store.async_save({"schemas": self._schemas})
        return True


class StatsStore:
    """Per-sender extraction statistics stored in .storage/email_events_ha.stats."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the stats store."""
        self._store: Store[dict[str, Any]] = Store(hass, STATS_STORAGE_VERSION, STATS_STORAGE_KEY)
        self._stats: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load stats from storage."""
        data = await self._store.async_load()
        self._stats = (data or {}).get("stats", {})

    def get(self, key: str) -> dict[str, Any]:
        """Return stats for a key, returning empty stat dict if absent."""
        return dict(self._stats.get(key, _empty_stat()))

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Return a copy of all stats."""
        return {k: dict(v) for k, v in self._stats.items()}

    def hit_rate(self, key: str) -> float | None:
        """Return match percentage for a key, or None if no emails processed."""
        stat = self._stats.get(key)
        if not stat or stat["total_processed"] == 0:
            return None
        return round(stat["total_matched"] / stat["total_processed"] * 100, 1)

    async def async_record(self, key: str, confidence: str, matched: bool) -> None:
        """Increment counters for key after processing an email."""
        stat = self._stats.setdefault(key, _empty_stat())
        stat["total_processed"] += 1
        if matched:
            stat["total_matched"] += 1
            conf_key = f"confidence_{confidence}" if confidence != CONFIDENCE_LOW else "confidence_low"
            stat[conf_key] = stat.get(conf_key, 0) + 1
            stat["last_matched_at"] = datetime.now(timezone.utc).isoformat()
        await self._store.async_save({"stats": self._stats})

    async def async_reset(self, key: str | None = None) -> None:
        """Reset stats for a single key, or all keys if key is None."""
        if key is not None:
            self._stats.pop(key, None)
        else:
            self._stats = {}
        await self._store.async_save({"stats": self._stats})
