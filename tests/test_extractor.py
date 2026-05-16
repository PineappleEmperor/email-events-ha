"""Unit tests for the extractor module."""
from __future__ import annotations

from typing import Any

import pytest

from custom_components.email_events_ha.const import (
    CHANGE_TYPE_NEW,
    CONFIDENCE_HIGH,
    SCHEMA_GENERIC,
    SCHEMA_PHOREST,
    SCHEMA_SPECSAVERS,
)
from custom_components.email_events_ha.extractor import (
    _clean_subject,
    _extract_datetimes,
    _extract_location,
    extract_calendar_change,
    extract_event,
    is_gcal_notification,
)

# ---------------------------------------------------------------------------
# is_gcal_notification
# ---------------------------------------------------------------------------


def test_gcal_sender_detected() -> None:
    """Known GCal sender returns True."""
    assert is_gcal_notification("calendar-notification@google.com") is True
    assert is_gcal_notification("CALENDAR-NOTIFICATION@GOOGLE.COM") is True


def test_non_gcal_sender_rejected() -> None:
    """Non-GCal sender returns False."""
    assert is_gcal_notification("noreply@specsavers.com") is False


# ---------------------------------------------------------------------------
# _clean_subject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "expected_contains"),
    [
        ("Dan, your contact lens health check is coming up", "contact lens health check"),
        ("Your appointment is coming up", "appointment"),
        ("Booking Confirmation for Dan at Chameleons", "at Chameleons"),
        ("Normal subject with no prefix", "Normal subject"),
    ],
)
def test_clean_subject(subject: str, expected_contains: str) -> None:
    """Prefixes and suffixes are stripped."""
    assert expected_contains in _clean_subject(subject)


# ---------------------------------------------------------------------------
# _extract_datetimes
# ---------------------------------------------------------------------------


def test_extract_datetime_with_time() -> None:
    """Date and time parsed from a body line."""
    body = "Your appointment is on Saturday 28 February 2026 at 12:30\n"
    start, end = _extract_datetimes(body)
    assert start is not None
    assert "2026-02-28" in start
    assert "12:30" in start
    assert end is None


def test_extract_datetime_time_range() -> None:
    """Time range produces start and end."""
    body = "When: 14:00 – 15:00 on 15 May 2026\n"
    start, end = _extract_datetimes(body)
    assert start is not None
    assert end is not None
    assert "14:00" in start
    assert "15:00" in end


def test_extract_datetime_date_only() -> None:
    """Date-only line returns midnight ISO string."""
    body = "We look forward to seeing you on 18 Apr 2026.\n"
    start, end = _extract_datetimes(body)
    assert start is not None
    assert "2026-04-18" in start
    assert start.endswith("T00:00:00")
    assert end is None


def test_extract_datetime_no_date() -> None:
    """Body with no date returns (None, None)."""
    body = "Thank you for your purchase. Please keep this receipt.\n"
    start, end = _extract_datetimes(body)
    assert start is None
    assert end is None


# ---------------------------------------------------------------------------
# _extract_location
# ---------------------------------------------------------------------------


def test_extract_location_at_pattern() -> None:
    """'at Place' pattern captured."""
    body = "Your appointment is confirmed\nat Specsavers Cheltenham\n"
    location = _extract_location(body)
    assert location is not None
    assert "Specsavers Cheltenham" in location


def test_extract_location_postcode_block() -> None:
    """UK postcode triggers address block extraction."""
    body = "James\nChameleons\n28 Clarence Street\nCheltenham\nGL50 3NX\n"
    location = _extract_location(body)
    assert location is not None
    assert "GL50 3NX" in location


def test_extract_location_none() -> None:
    """No location indicators returns None."""
    body = "Thanks for your booking. See you soon!\n"
    assert _extract_location(body) is None


# ---------------------------------------------------------------------------
# extract_event — generic schema
# ---------------------------------------------------------------------------


def test_extract_event_generic_returns_none_without_date(specsavers_email: dict[str, Any]) -> None:
    """Email with no date in body returns None."""
    email = {**specsavers_email, "body_text": "Thanks for booking. See you soon!"}
    assert extract_event(email) is None


def test_extract_event_generic_high_confidence(specsavers_email: dict[str, Any]) -> None:
    """Date + time + location gives high confidence."""
    result = extract_event(specsavers_email, schema=SCHEMA_GENERIC)
    assert result is not None
    assert result.confidence == CONFIDENCE_HIGH
    assert result.uid == specsavers_email["uid"]
    assert result.source_email == specsavers_email["sender_email"]


# ---------------------------------------------------------------------------
# extract_event — specsavers schema
# ---------------------------------------------------------------------------


def test_extract_event_specsavers_time_date_pattern(specsavers_email: dict[str, Any]) -> None:
    """Specsavers schema parses '12:30 - Saturday, 28 February 2026'."""
    result = extract_event(specsavers_email, schema=SCHEMA_SPECSAVERS)
    assert result is not None
    assert "2026-02-28" in (result.start_datetime or "")
    assert "12:30" in (result.start_datetime or "")


def test_extract_event_specsavers_date_time_pattern() -> None:
    """Specsavers schema parses 'is on Saturday 28 February 2026 at 12:30'."""
    email = {
        "uid": "1",
        "subject": "Your eye test is coming up",
        "sender_email": "noreply@specsavers.com",
        "sender_name": "Specsavers",
        "date": "2026-01-01T00:00:00",
        "body_text": "Your eye test is on Saturday 28 February 2026 at 09:00\nat Specsavers Gloucester\n",
    }
    result = extract_event(email, schema=SCHEMA_SPECSAVERS)
    assert result is not None
    assert "2026-02-28" in (result.start_datetime or "")
    assert "09:00" in (result.start_datetime or "")


def test_extract_event_specsavers_falls_back_to_generic() -> None:
    """Specsavers schema falls back to generic when its patterns don't match."""
    email = {
        "uid": "2",
        "subject": "Reminder",
        "sender_email": "noreply@specsavers.com",
        "sender_name": "Specsavers",
        "date": "2026-01-01T00:00:00",
        "body_text": "Your appointment is on 10 March 2026.\n",
    }
    result = extract_event(email, schema=SCHEMA_SPECSAVERS)
    assert result is not None
    assert "2026-03-10" in (result.start_datetime or "")


# ---------------------------------------------------------------------------
# extract_event — phorest schema
# ---------------------------------------------------------------------------


def test_extract_event_phorest(phorest_email: dict[str, Any]) -> None:
    """Phorest schema extracts date from 'seeing you on' pattern."""
    result = extract_event(phorest_email, schema=SCHEMA_PHOREST)
    assert result is not None
    assert "2026-04-18" in (result.start_datetime or "")
    assert result.start_datetime is not None
    assert result.start_datetime.endswith("T00:00:00")


def test_extract_event_phorest_location_from_postcode(phorest_email: dict[str, Any]) -> None:
    """Phorest schema picks up location via postcode fallback."""
    result = extract_event(phorest_email, schema=SCHEMA_PHOREST)
    assert result is not None
    assert result.location is not None
    assert "GL50" in result.location


# ---------------------------------------------------------------------------
# extract_calendar_change
# ---------------------------------------------------------------------------


def test_extract_calendar_change_invitation(gcal_email: dict[str, Any]) -> None:
    """Invitation subject parsed as new change."""
    result = extract_calendar_change(gcal_email)
    assert result is not None
    assert result.change_type == CHANGE_TYPE_NEW
    assert "Team meeting" in result.event_title


def test_extract_calendar_change_when_field(gcal_email: dict[str, Any]) -> None:
    """'When:' field extracted as start_datetime."""
    result = extract_calendar_change(gcal_email)
    assert result is not None
    assert result.start_datetime is not None
    assert "2026-05-15" in result.start_datetime


def test_extract_calendar_change_organizer(gcal_email: dict[str, Any]) -> None:
    """Organizer field extracted."""
    result = extract_calendar_change(gcal_email)
    assert result is not None
    assert result.organizer == "alice@example.com"


def test_extract_calendar_change_calendar_name(gcal_email: dict[str, Any]) -> None:
    """Calendar name extracted."""
    result = extract_calendar_change(gcal_email)
    assert result is not None
    assert result.calendar_name == "Work"


@pytest.mark.parametrize(
    ("subject", "expected_type"),
    [
        ("Updated invitation: Team meeting @ Fri 15 May", "update"),
        ("Cancelled event: Team meeting @ Fri 15 May", "cancel"),
        ("Accepted: Team meeting @ Fri 15 May", "new"),
    ],
)
def test_extract_calendar_change_types(
    gcal_email: dict[str, Any], subject: str, expected_type: str
) -> None:
    """All change type subjects parsed correctly."""
    email = {**gcal_email, "subject": subject}
    result = extract_calendar_change(email)
    assert result is not None
    assert result.change_type == expected_type


def test_extract_calendar_change_unrecognised_subject() -> None:
    """Non-GCal subject returns None."""
    email = {
        "uid": "x",
        "subject": "Random email subject",
        "sender_email": "calendar-notification@google.com",
        "date": None,
        "body_text": "",
    }
    assert extract_calendar_change(email) is None
