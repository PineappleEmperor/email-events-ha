"""Coordinator for Email Events HA."""
from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    BUILTIN_SCHEMAS,
    CONF_EMAIL_HA_ENTRY_ID,
    CONF_EMAIL_NAMES,
    CONF_NAME_DISPLAY,
    CONF_NAME_EMAIL,
    CONF_RULE_SCHEMA,
    CONF_RULE_SENDER,
    CONF_SENDER_FILTER,
    CONF_SENDER_RULES,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DOMAIN,
    EMAIL_HA_CONF_EMAIL,
    EMAIL_HA_DOMAIN,
    EMAIL_HA_EVENT_NEW_EMAIL,
    EMAIL_HA_SERVICE_QUERY,
    SCHEMA_GCAL,
    SCHEMA_GENERIC,
)
from .extractor import (
    CalendarChange,
    DetectedEvent,
    extract_calendar_change,
    extract_event,
    is_gcal_subject,
)
from .storage import SchemaStore, StatsStore

_LOGGER = logging.getLogger(__name__)


_GCAL_AUTO_SENDERS: frozenset[str] = frozenset(
    s.lower() for s in BUILTIN_SCHEMAS[SCHEMA_GCAL]["auto_senders"]
)


class EmailEventsCoordinator:
    """Listens for email_ha new-email events, extracts calendar event data."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        schema_store: SchemaStore | None = None,
        stats_store: StatsStore | None = None,
    ) -> None:
        """Set up coordinator state."""
        self.hass = hass
        self._entry = entry
        self._schema_store = schema_store
        self._stats_store = stats_store
        domain_data: dict = hass.data.get(DOMAIN, {})
        self.last_event: DetectedEvent | None = domain_data.get("last_event")
        self.last_calendar_change: CalendarChange | None = domain_data.get("last_calendar_change")
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: Callable[[], None] | None = None
        self._monitored_email: str | None = None
        self._sender_filter: set[str] = set()
        self._sender_rules: list[dict[str, str]] = []
        self._name_map: dict[str, str] = {}

    @property
    def sender_rules(self) -> list[dict[str, str]]:
        """Return configured sender→schema rules."""
        return self._sender_rules

    async def async_setup(self) -> None:
        """Resolve the watched email address and subscribe to bus events."""
        email_ha_entry_id: str = self._entry.data[CONF_EMAIL_HA_ENTRY_ID]

        for e in self.hass.config_entries.async_entries(EMAIL_HA_DOMAIN):
            if e.entry_id == email_ha_entry_id:
                self._monitored_email = e.data.get(EMAIL_HA_CONF_EMAIL)
                break

        raw_filter: str = self._entry.options.get(
            CONF_SENDER_FILTER,
            self._entry.data.get(CONF_SENDER_FILTER, ""),
        )
        self._sender_filter = {
            s.strip().lower() for s in raw_filter.split(",") if s.strip()
        }
        self._sender_rules = list(self._entry.options.get(CONF_SENDER_RULES, []))
        self._name_map = {
            n[CONF_NAME_EMAIL].lower(): n[CONF_NAME_DISPLAY]
            for n in self._entry.options.get(CONF_EMAIL_NAMES, [])
            if n.get(CONF_NAME_EMAIL) and n.get(CONF_NAME_DISPLAY)
        }

        self._unsubscribe = self.hass.bus.async_listen(
            EMAIL_HA_EVENT_NEW_EMAIL,
            self._handle_new_email,
        )
        _LOGGER.debug(
            "Subscribed to %s for account %s (sender_filter=%s)",
            EMAIL_HA_EVENT_NEW_EMAIL,
            self._monitored_email,
            self._sender_filter or "all",
        )

    async def async_shutdown(self) -> None:
        """Unsubscribe from bus events."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def async_add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a listener; returns an unregister callable."""
        self._listeners.append(callback)

        def _remove() -> None:
            self._listeners.remove(callback)

        return _remove

    def notify_listeners(self) -> None:
        """Notify all registered listeners of a state change."""
        for callback in self._listeners:
            callback()

    async def _handle_new_email(self, event: Event) -> None:
        data: dict[str, Any] = event.data

        if self._monitored_email and data.get("email_address") != self._monitored_email:
            return

        sender_email: str = (data.get("sender_email") or "").lower()
        uid: str = data.get("uid") or ""
        folder: str = data.get("folder") or "INBOX"

        if not uid:
            return

        gcal_sender = sender_email in _GCAL_AUTO_SENDERS
        subject: str = (data.get("subject") or "").strip()
        gcal = gcal_sender or is_gcal_subject(subject)

        if not gcal and self._sender_filter and sender_email not in self._sender_filter:
            _LOGGER.debug("Skipping email from %s (not in sender filter)", sender_email)
            return

        email_data = await self._fetch_full_email(uid, folder)
        if not email_data:
            return

        if gcal:
            change = extract_calendar_change(email_data)
            if change:
                change.recipient_email = self._monitored_email
            if self._stats_store:
                await self._stats_store.async_record(SCHEMA_GCAL, CONFIDENCE_HIGH, bool(change))
            if change:
                change.recipient_email = self._resolve_name(change.recipient_email)
                change.changed_by = self._resolve_name(change.changed_by)
                change.organizer = self._resolve_name(change.organizer)
                self.last_calendar_change = change
                self.hass.data[DOMAIN]["last_calendar_change"] = change
                _LOGGER.debug("Calendar change extracted: %s (%s)", change.event_title, change.change_type)
                self.notify_listeners()
        else:
            schema, patterns = self._resolve_schema(sender_email)
            detected = extract_event(email_data, schema=schema, patterns=patterns)
            if self._stats_store:
                confidence = detected.confidence if detected else CONFIDENCE_LOW
                await self._stats_store.async_record(sender_email, confidence, bool(detected))
            if detected:
                detected.organizer = self._resolve_name(detected.organizer)
                self.last_event = detected
                self.hass.data[DOMAIN]["last_event"] = detected
                _LOGGER.debug("Event extracted: %s (confidence=%s)", detected.title, detected.confidence)
                self.notify_listeners()

    def _resolve_name(self, email: str | None) -> str | None:
        """Return display name for an email address, or the raw email if unmapped."""
        if not email:
            return None
        resolved = self._name_map.get(email.lower())
        if resolved is None and email:
            _LOGGER.info("Unrecognised identity %s — add to email name mappings", email)
        return resolved or email

    def _schema_for_sender(self, sender_email: str) -> str:
        """Return configured schema name for a sender, defaulting to generic."""
        for rule in self._sender_rules:
            if rule.get(CONF_RULE_SENDER) == sender_email:
                return rule.get(CONF_RULE_SCHEMA, SCHEMA_GENERIC)
        return SCHEMA_GENERIC

    def _resolve_schema(self, sender_email: str) -> tuple[str, list[str] | None]:
        """Return (schema_id, patterns) for a sender; patterns=None uses builtin lookup."""
        schema_id = self._schema_for_sender(sender_email)
        if self._schema_store:
            user_def = self._schema_store.get(schema_id)
            if user_def:
                return schema_id, user_def.get("patterns", [])
        return schema_id, None

    async def _fetch_full_email(self, uid: str, folder: str) -> dict[str, Any] | None:
        """Call email_ha.query_emails to retrieve full body for a given UID."""
        email_ha_entry_id: str = self._entry.data[CONF_EMAIL_HA_ENTRY_ID]
        try:
            result = await self.hass.services.async_call(
                EMAIL_HA_DOMAIN,
                EMAIL_HA_SERVICE_QUERY,
                {
                    "config_entry_id": email_ha_entry_id,
                    "folder": folder,
                    "search_criteria": f"UID {uid}",
                    "max_results": 1,
                    "include_full_body": True,
                },
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to fetch email body uid=%s: %s", uid, err)
            return None

        emails: list[dict[str, Any]] = (result or {}).get("emails", [])
        if emails:
            _LOGGER.debug("email_ha fields for uid=%s: %s", uid, list(emails[0].keys()))
        return emails[0] if emails else None
