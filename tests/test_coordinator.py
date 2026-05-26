"""Tests for EmailEventsCoordinator routing and filtering logic."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.email_events_ha.const import (
    CONF_RULE_SCHEMA,
    CONF_RULE_SENDER,
    CONF_SENDER_RULES,
    SCHEMA_GENERIC,
    SCHEMA_SPECSAVERS,
)
from custom_components.email_events_ha.coordinator import EmailEventsCoordinator

from .conftest import MOCK_EMAIL_ADDRESS, MOCK_EMAIL_HA_ENTRY_ID


def _make_coordinator(
    sender_filter: str = "",
    sender_rules: list[dict[str, str]] | None = None,
    email_address: str = MOCK_EMAIL_ADDRESS,
) -> tuple[EmailEventsCoordinator, MagicMock]:
    """Build a coordinator with mocked hass and config entry."""
    hass = MagicMock()
    hass.data = {"email_events_ha": {"last_event": None, "last_calendar_change": None}}
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.config_entries.async_entries = MagicMock(
        return_value=[
            MagicMock(entry_id=MOCK_EMAIL_HA_ENTRY_ID, data={"email": email_address})
        ]
    )

    entry = MagicMock()
    entry.entry_id = "events_entry"
    entry.data = {"email_ha_entry_id": MOCK_EMAIL_HA_ENTRY_ID, "sender_filter": sender_filter}
    entry.options = {
        "sender_filter": sender_filter,
        CONF_SENDER_RULES: sender_rules or [],
    }

    coordinator = EmailEventsCoordinator(hass, entry)
    return coordinator, hass


# ---------------------------------------------------------------------------
# _schema_for_sender
# ---------------------------------------------------------------------------


def test_schema_for_sender_match() -> None:
    """Configured sender returns its assigned schema."""
    coordinator, _ = _make_coordinator(
        sender_rules=[{CONF_RULE_SENDER: "noreply@specsavers.com", CONF_RULE_SCHEMA: SCHEMA_SPECSAVERS}]
    )
    coordinator._sender_rules = [{CONF_RULE_SENDER: "noreply@specsavers.com", CONF_RULE_SCHEMA: SCHEMA_SPECSAVERS}]
    assert coordinator._schema_for_sender("noreply@specsavers.com") == SCHEMA_SPECSAVERS


def test_schema_for_sender_no_match() -> None:
    """Unknown sender returns generic."""
    coordinator, _ = _make_coordinator()
    assert coordinator._schema_for_sender("unknown@example.com") == SCHEMA_GENERIC


# ---------------------------------------------------------------------------
# _handle_new_email — account filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_ignores_different_account() -> None:
    """Email for a different account is ignored."""
    coordinator, hass = _make_coordinator()
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS
    coordinator._sender_filter = set()
    coordinator._sender_rules = []

    fetch_called = False

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        nonlocal fetch_called
        fetch_called = True
        return None

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {
        "email_address": "other@gmail.com",
        "sender_email": "shop@example.com",
        "uid": "111",
        "folder": "INBOX",
    }
    await coordinator._handle_new_email(event)
    assert not fetch_called


@pytest.mark.asyncio
async def test_handle_ignores_sender_not_in_filter() -> None:
    """Email from sender not in filter is skipped."""
    coordinator, _ = _make_coordinator(sender_filter="allowed@example.com")
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS
    coordinator._sender_filter = {"allowed@example.com"}
    coordinator._sender_rules = []

    fetch_called = False

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        nonlocal fetch_called
        fetch_called = True
        return None

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {
        "email_address": MOCK_EMAIL_ADDRESS,
        "sender_email": "other@example.com",
        "uid": "222",
        "folder": "INBOX",
    }
    await coordinator._handle_new_email(event)
    assert not fetch_called


@pytest.mark.asyncio
async def test_handle_gcal_bypasses_sender_filter() -> None:
    """GCal notification is processed even when sender filter is active."""
    coordinator, _ = _make_coordinator(sender_filter="allowed@example.com")
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS
    coordinator._sender_filter = {"allowed@example.com"}
    coordinator._sender_rules = []

    fetched_uid = None

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        nonlocal fetched_uid
        fetched_uid = uid
        return {
            "uid": uid,
            "subject": "Invitation: Standup @ Fri 15 May 2026",
            "sender_email": "calendar-notification@google.com",
            "date": "2026-05-01T00:00:00",
            "body_text": "When: Friday, 15 May 2026 09:00\nCalendar: Work\n",
        }

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {
        "email_address": MOCK_EMAIL_ADDRESS,
        "sender_email": "calendar-notification@google.com",
        "uid": "333",
        "folder": "INBOX",
    }
    await coordinator._handle_new_email(event)
    assert fetched_uid == "333"
    assert coordinator.last_calendar_change is not None


@pytest.mark.asyncio
async def test_handle_routes_gcal_to_calendar_change() -> None:
    """GCal email updates last_calendar_change, not last_event."""
    coordinator, _ = _make_coordinator()
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS
    coordinator._sender_filter = set()
    coordinator._sender_rules = []

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        return {
            "uid": uid,
            "subject": "Invitation: Sprint review @ Mon 20 May 2026",
            "sender_email": "calendar-notification@google.com",
            "date": "2026-05-01T00:00:00",
            "body_text": "When: Monday, 20 May 2026 14:00\nCalendar: Team\nOrganizer: bob@example.com\n",
        }

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {
        "email_address": MOCK_EMAIL_ADDRESS,
        "sender_email": "calendar-notification@google.com",
        "uid": "444",
        "folder": "INBOX",
    }
    await coordinator._handle_new_email(event)
    assert coordinator.last_calendar_change is not None
    assert coordinator.last_event is None


@pytest.mark.asyncio
async def test_handle_routes_booking_to_last_event(specsavers_email: Any) -> None:
    """Booking email updates last_event, not last_calendar_change."""
    coordinator, _ = _make_coordinator()
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS
    coordinator._sender_filter = set()
    coordinator._sender_rules = []

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        return specsavers_email

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {
        "email_address": MOCK_EMAIL_ADDRESS,
        "sender_email": specsavers_email["sender_email"],
        "uid": specsavers_email["uid"],
        "folder": "INBOX",
    }
    await coordinator._handle_new_email(event)
    assert coordinator.last_event is not None
    assert coordinator.last_calendar_change is None


@pytest.mark.asyncio
async def test_handle_skips_missing_uid() -> None:
    """Event without UID is silently skipped."""
    coordinator, _ = _make_coordinator()
    coordinator._monitored_email = MOCK_EMAIL_ADDRESS

    fetch_called = False

    async def mock_fetch(uid: str, folder: str) -> dict[str, Any] | None:
        nonlocal fetch_called
        fetch_called = True
        return None

    coordinator._fetch_full_email = mock_fetch  # type: ignore[method-assign]

    event = MagicMock()
    event.data = {"email_address": MOCK_EMAIL_ADDRESS, "sender_email": "x@x.com", "uid": "", "folder": "INBOX"}
    await coordinator._handle_new_email(event)
    assert not fetch_called
