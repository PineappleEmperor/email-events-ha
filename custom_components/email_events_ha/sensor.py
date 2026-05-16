"""Sensor platform for Email Events HA."""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CALENDAR_NAME,
    ATTR_CHANGE_TYPE,
    ATTR_CHANGED_BY,
    ATTR_CONFIDENCE,
    ATTR_END_DATETIME,
    ATTR_EVENT_TITLE,
    ATTR_EXTRACTED_AT,
    ATTR_LOCATION,
    ATTR_ORGANIZER,
    ATTR_RAW_SUBJECT,
    ATTR_RECIPIENT_EMAIL,
    ATTR_SENT_DATETIME,
    ATTR_SOURCE_EMAIL,
    ATTR_START_DATETIME,
    ATTR_UID,
    CONF_EMAIL_HA_ENTRY_ID,
    CONF_RULE_SCHEMA,
    CONF_RULE_SENDER,
    DOMAIN,
    EMAIL_HA_DOMAIN,
    SCHEMA_GCAL,
)
from .coordinator import EmailEventsCoordinator
from .storage import StatsStore

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Email Events HA sensors for a config entry."""
    coordinator: EmailEventsCoordinator = hass.data[DOMAIN][entry.entry_id]
    stats_store: StatsStore = hass.data[DOMAIN]["stats_store"]

    entities: list[SensorEntity] = [
        LastDetectedEventSensor(coordinator, entry),
        LastCalendarChangeSensor(coordinator, entry),
        HitRateSensor(coordinator, entry, stats_store, SCHEMA_GCAL, "Google Calendar hit rate"),
    ]
    for rule in coordinator.sender_rules:
        sender = rule[CONF_RULE_SENDER]
        schema = rule.get(CONF_RULE_SCHEMA, "")
        label = f"{sender} ({schema}) hit rate" if schema else f"{sender} hit rate"
        entities.append(HitRateSensor(coordinator, entry, stats_store, sender, label))

    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    email_ha_entry_id: str = entry.data[CONF_EMAIL_HA_ENTRY_ID]
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Email Events – {entry.title}",
        manufacturer="Email Events HA",
        model="Event Extractor",
        entry_type=DeviceEntryType.SERVICE,
        via_device=(EMAIL_HA_DOMAIN, email_ha_entry_id),
    )


class _BaseEventSensor(SensorEntity):
    """Base sensor that updates when the coordinator notifies."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: EmailEventsCoordinator,
        entry: ConfigEntry,
        unique_suffix: str,
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = _device_info(entry)
        self._remove_listener: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.async_add_listener(
            self._on_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _on_coordinator_update(self) -> None:
        self.async_write_ha_state()


class LastDetectedEventSensor(_BaseEventSensor):
    """Most recently extracted event from a booking/appointment email."""

    _attr_name = "Last detected event"
    _attr_icon = "mdi:calendar-plus"

    def __init__(self, coordinator: EmailEventsCoordinator, entry: ConfigEntry) -> None:
        """Set up last detected event sensor."""
        super().__init__(coordinator, entry, "last_detected_event")

    @property
    def native_value(self) -> str | None:
        """Return cleaned event title."""
        evt = self._coordinator.last_event
        return evt.title if evt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extracted event details."""
        evt = self._coordinator.last_event
        if not evt:
            return {}
        return {
            ATTR_START_DATETIME: evt.start_datetime,
            ATTR_END_DATETIME: evt.end_datetime,
            ATTR_LOCATION: evt.location,
            ATTR_ORGANIZER: evt.organizer,
            ATTR_SOURCE_EMAIL: evt.source_email,
            ATTR_RAW_SUBJECT: evt.raw_subject,
            ATTR_UID: evt.uid,
            ATTR_SENT_DATETIME: evt.sent_datetime,
            ATTR_CONFIDENCE: evt.confidence,
            ATTR_EXTRACTED_AT: evt.extracted_at,
        }


class LastCalendarChangeSensor(_BaseEventSensor):
    """Most recently detected Google Calendar change notification."""

    _attr_name = "Last calendar change"
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, coordinator: EmailEventsCoordinator, entry: ConfigEntry) -> None:
        """Set up last calendar change sensor."""
        super().__init__(coordinator, entry, "last_calendar_change")

    @property
    def native_value(self) -> str | None:
        """Return the changed event title."""
        change = self._coordinator.last_calendar_change
        return change.event_title if change else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return calendar change details."""
        change = self._coordinator.last_calendar_change
        if not change:
            return {}
        return {
            ATTR_EVENT_TITLE: change.event_title,
            ATTR_CHANGE_TYPE: change.change_type,
            ATTR_START_DATETIME: change.start_datetime,
            ATTR_ORGANIZER: change.organizer,
            ATTR_CALENDAR_NAME: change.calendar_name,
            ATTR_CHANGED_BY: change.changed_by,
            ATTR_RECIPIENT_EMAIL: change.recipient_email,
            ATTR_SOURCE_EMAIL: change.source_email,
            ATTR_UID: change.uid,
            ATTR_SENT_DATETIME: change.sent_datetime,
            ATTR_EXTRACTED_AT: change.extracted_at,
        }


class HitRateSensor(_BaseEventSensor):
    """Diagnostic sensor showing extraction hit rate for one sender/schema pairing."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:chart-bar"

    def __init__(
        self,
        coordinator: EmailEventsCoordinator,
        entry: ConfigEntry,
        stats_store: StatsStore,
        stats_key: str,
        label: str,
    ) -> None:
        """Set up hit-rate sensor for a sender key."""
        safe_key = stats_key.replace("@", "_at_").replace(".", "_").replace(" ", "_")
        super().__init__(coordinator, entry, f"hit_rate_{safe_key}")
        self._stats_store = stats_store
        self._stats_key = stats_key
        self._attr_name = label

    @property
    def native_value(self) -> float | None:
        """Return match rate as a percentage, or None if no emails processed."""
        return self._stats_store.hit_rate(self._stats_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw stat counters."""
        return self._stats_store.get(self._stats_key)
