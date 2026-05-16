"""Shared test fixtures for Email Events HA."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.email_events_ha.const import (
    CONF_EMAIL_HA_ENTRY_ID,
    CONF_SENDER_FILTER,
    CONF_SENDER_RULES,
)

MOCK_ENTRY_ID = "test_entry_id"
MOCK_EMAIL_HA_ENTRY_ID = "email_ha_entry_id_1"
MOCK_EMAIL_ADDRESS = "test@gmail.com"


@pytest.fixture
def mock_email_ha_entry() -> MagicMock:
    """Return a mock email_ha config entry."""
    entry = MagicMock()
    entry.entry_id = MOCK_EMAIL_HA_ENTRY_ID
    entry.data = {"email": MOCK_EMAIL_ADDRESS}
    return entry


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Return a mock email_events_ha config entry."""
    entry = MagicMock()
    entry.entry_id = MOCK_ENTRY_ID
    entry.data = {
        CONF_EMAIL_HA_ENTRY_ID: MOCK_EMAIL_HA_ENTRY_ID,
        CONF_SENDER_FILTER: "",
    }
    entry.options = {
        CONF_SENDER_FILTER: "",
        CONF_SENDER_RULES: [],
    }
    return entry


@pytest.fixture
def specsavers_email() -> dict[str, Any]:
    """Return a realistic Specsavers appointment email payload."""
    return {
        "uid": "99001",
        "subject": "Dan, your contact lens health check is coming up",
        "sender_name": "Specsavers Cheltenham",
        "sender_email": "noreply@specsavers.com",
        "date": "2026-02-01T09:00:00",
        "body_text": (
            "Your contact lens health check is confirmed for:\n"
            "12:30 - Saturday, 28 February 2026\n"
            "at Specsavers Cheltenham\n"
            "206 High Street\n"
            "Cheltenham\n"
            "GL50 1JB\n"
        ),
    }


@pytest.fixture
def phorest_email() -> dict[str, Any]:
    """Return a realistic Phorest booking confirmation email payload."""
    return {
        "uid": "99002",
        "subject": "Booking Confirmation for Dan at Chameleons",
        "sender_name": "Chameleons",
        "sender_email": "noreply@phorest.com",
        "date": "2026-04-10T08:00:00",
        "body_text": (
            "Hi Dan,\n"
            "Thanks for booking your appointment with Chameleons. "
            "We look forward to seeing you on 18 Apr 2026.\n"
            "James\n"
            "Chameleons\n"
            "28 Clarence Street\n"
            "Cheltenham\n"
            "Gloucestershire\n"
            "GL50 3NX\n"
        ),
    }


@pytest.fixture
def gcal_email() -> dict[str, Any]:
    """Return a Google Calendar invitation email payload."""
    return {
        "uid": "99003",
        "subject": "Invitation: Team meeting @ Fri 15 May 2026 2pm",
        "sender_name": "Google Calendar",
        "sender_email": "calendar-notification@google.com",
        "date": "2026-05-10T10:00:00",
        "body_text": (
            "Team meeting\n"
            "When: Friday, 15 May 2026 14:00 – 15:00\n"
            "Where: Meeting room 1\n"
            "Calendar: Work\n"
            "Organizer: alice@example.com\n"
        ),
    }
