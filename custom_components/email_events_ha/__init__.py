"""Email Events HA integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS
from .coordinator import EmailEventsCoordinator
from .services import async_register_services
from .storage import SchemaStore, StatsStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Email Events HA from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    if "schema_store" not in hass.data[DOMAIN]:
        schema_store = SchemaStore(hass)
        await schema_store.async_load()
        hass.data[DOMAIN]["schema_store"] = schema_store

    if "stats_store" not in hass.data[DOMAIN]:
        stats_store = StatsStore(hass)
        await stats_store.async_load()
        hass.data[DOMAIN]["stats_store"] = stats_store

    hass.data[DOMAIN].setdefault("last_event", None)
    hass.data[DOMAIN].setdefault("last_calendar_change", None)

    await async_register_services(hass)

    coordinator = EmailEventsCoordinator(
        hass,
        entry,
        schema_store=hass.data[DOMAIN]["schema_store"],
        stats_store=hass.data[DOMAIN]["stats_store"],
    )
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform(p) for p in PLATFORMS]
    )

    entry.async_on_unload(coordinator.async_shutdown)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change so coordinator picks up new rules."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(
        entry, [Platform(p) for p in PLATFORMS]
    )
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
