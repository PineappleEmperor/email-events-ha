"""Service handlers for Email Events HA."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from .const import (
    BUILTIN_SCHEMAS,
    DOMAIN,
    SERVICE_CREATE_SCHEMA,
    SERVICE_DELETE_SCHEMA,
    SERVICE_LIST_SCHEMAS,
    SERVICE_RELOAD_SCHEMAS,
    SERVICE_RESET_STATS,
    SERVICE_UPDATE_SCHEMA,
)
from .coordinator import EmailEventsCoordinator
from .storage import SchemaStore, StatsStore

_LOGGER = logging.getLogger(__name__)

_SCHEMA_FIELDS = vol.Schema(
    {
        vol.Required("schema_id"): str,
        vol.Optional("label"): str,
        vol.Optional("patterns", default=[]): [str],
    }
)

_DELETE_SCHEMA = vol.Schema({vol.Required("schema_id"): str})
_RESET_STATS_SCHEMA = vol.Schema({vol.Optional("sender"): str})


def _schema_store(hass: HomeAssistant) -> SchemaStore:
    """Return the domain-level schema store."""
    return hass.data[DOMAIN]["schema_store"]


def _stats_store(hass: HomeAssistant) -> StatsStore:
    """Return the domain-level stats store."""
    return hass.data[DOMAIN]["stats_store"]


async def async_register_services(hass: HomeAssistant) -> None:
    """Register all domain services; safe to call multiple times."""
    if hass.services.has_service(DOMAIN, SERVICE_LIST_SCHEMAS):
        return

    async def handle_create_schema(call: ServiceCall) -> None:
        """Create a new user-defined schema."""
        schema_id: str = call.data["schema_id"].strip()
        if schema_id in BUILTIN_SCHEMAS:
            raise HomeAssistantError(f"Cannot overwrite built-in schema '{schema_id}'")
        store = _schema_store(hass)
        await store.async_save_schema(schema_id, {
            "label": call.data.get("label", schema_id),
            "patterns": call.data.get("patterns", []),
        })
        _LOGGER.info("Created schema '%s'", schema_id)

    async def handle_update_schema(call: ServiceCall) -> None:
        """Update an existing user-defined schema."""
        schema_id: str = call.data["schema_id"].strip()
        if schema_id in BUILTIN_SCHEMAS:
            raise HomeAssistantError(f"Cannot modify built-in schema '{schema_id}'")
        store = _schema_store(hass)
        existing = store.get(schema_id) or {}
        updated = {
            "label": call.data.get("label", existing.get("label", schema_id)),
            "patterns": call.data.get("patterns", existing.get("patterns", [])),
        }
        await store.async_save_schema(schema_id, updated)
        _LOGGER.info("Updated schema '%s'", schema_id)

    async def handle_delete_schema(call: ServiceCall) -> None:
        """Delete a user-defined schema."""
        schema_id: str = call.data["schema_id"].strip()
        if schema_id in BUILTIN_SCHEMAS:
            raise HomeAssistantError(f"Cannot delete built-in schema '{schema_id}'")
        store = _schema_store(hass)
        if not await store.async_delete_schema(schema_id):
            raise HomeAssistantError(f"Schema '{schema_id}' not found")
        _LOGGER.info("Deleted schema '%s'", schema_id)

    async def handle_list_schemas(call: ServiceCall) -> dict[str, Any]:
        """Return all schemas (builtin + user) with stats."""
        store = _schema_store(hass)
        stats = _stats_store(hass)
        result: dict[str, Any] = {}

        for sid, sdef in BUILTIN_SCHEMAS.items():
            result[sid] = {
                "label": sdef["label"],
                "source": "builtin",
                "patterns": sdef.get("patterns", []),
                "stats": stats.get(sid),
            }

        for sid, sdef in store.get_all().items():
            result[sid] = {
                "label": sdef.get("label", sid),
                "source": "user",
                "patterns": sdef.get("patterns", []),
                "stats": stats.get(sid),
            }

        return result

    async def handle_reload_schemas(call: ServiceCall) -> None:
        """Reload user schemas from storage and restart all entries."""
        store = _schema_store(hass)
        await store.async_load()
        _LOGGER.info("Schemas reloaded from storage")
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_reload(entry.entry_id)

    async def handle_reset_stats(call: ServiceCall) -> None:
        """Reset extraction stats for a sender or all senders."""
        sender: str | None = call.data.get("sender")
        store = _stats_store(hass)
        await store.async_reset(sender)
        _LOGGER.info("Stats reset%s", f" for {sender}" if sender else " (all)")
        for value in hass.data.get(DOMAIN, {}).values():
            if isinstance(value, EmailEventsCoordinator):
                value.notify_listeners()

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_SCHEMA, handle_create_schema, schema=_SCHEMA_FIELDS
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_SCHEMA, handle_update_schema, schema=_SCHEMA_FIELDS
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_SCHEMA, handle_delete_schema, schema=_DELETE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_SCHEMAS,
        handle_list_schemas,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RELOAD_SCHEMAS, handle_reload_schemas
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_STATS, handle_reset_stats, schema=_RESET_STATS_SCHEMA
    )
