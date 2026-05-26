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
    _parse_ics_datetimes,
    extract_calendar_change,
    extract_event,
    is_gcal_notification,
    is_gcal_subject,
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


def test_gcal_subject_detected() -> None:
    """GCal-style subjects recognised regardless of sender."""
    assert is_gcal_subject("New event: Team lunch @ Fri 30 May") is True
    assert is_gcal_subject("Canceled event: Team lunch @ Fri 30 May") is True
    assert is_gcal_subject("Updated invitation: Sprint review @ Thu") is True
    assert is_gcal_subject("Accepted: Weekly sync @ Mon") is True


def test_gcal_subject_rejected() -> None:
    """Non-GCal subjects return False."""
    assert is_gcal_subject("Your appointment is confirmed") is False
    assert is_gcal_subject("Booking confirmation for Dan") is False


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
        ("New event: Test @ Tue May 26, 2026 8pm", "Test"),
        ("Invitation: Team standup @ Mon Jun 1", "Team standup"),
        ("Updated invitation: Sprint planning @ Wed", "Sprint planning"),
        ("Cancelled event: Friday drinks @ Fri", "Friday drinks"),
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


def test_extract_datetime_ampm_range() -> None:
    """AM/PM time range like '8pm - 9pm' on a date line is parsed correctly."""
    body = "When: Tue May 26, 2026 8pm - 9pm (BST)\n"
    start, end = _extract_datetimes(body)
    assert start is not None and "2026-05-26" in start and "20:00:00" in start
    assert end is not None and "21:00:00" in end


def test_extract_datetime_ampm_single() -> None:
    """Single AM/PM time like '2:30pm' on a date line is parsed."""
    body = "Appointment: 15 June 2026 at 2:30pm\n"
    start, end = _extract_datetimes(body)
    assert start is not None and "14:30:00" in start
    assert end is None


def test_extract_datetime_ampm_noon_midnight() -> None:
    """12pm = noon (12:00), 12am = midnight (00:00)."""
    body = "Event on 1 January 2026 12pm - 12am\n"
    start, end = _extract_datetimes(body)
    assert start is not None and "12:00:00" in start
    assert end is not None and "00:00:00" in end


# ---------------------------------------------------------------------------
# _parse_ics_datetimes
# ---------------------------------------------------------------------------


def test_parse_ics_datetimes_utc() -> None:
    """UTC DTSTART/DTEND parsed to ISO with timezone offset."""
    body = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART:20260522T140000Z\r\n"
        "DTEND:20260522T150000Z\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    start, end = _parse_ics_datetimes(body)
    assert start is not None and "2026-05-22" in start and "14:00:00" in start
    assert end is not None and "2026-05-22" in end and "15:00:00" in end


def test_parse_ics_datetimes_naive() -> None:
    """Naive DTSTART without Z parsed correctly."""
    body = (
        "BEGIN:VCALENDAR\r\n"
        "DTSTART;TZID=Europe/London:20260522T140000\r\n"
        "DTEND;TZID=Europe/London:20260522T150000\r\n"
        "END:VCALENDAR\r\n"
    )
    start, end = _parse_ics_datetimes(body)
    assert start == "2026-05-22T14:00:00"
    assert end == "2026-05-22T15:00:00"


def test_parse_ics_datetimes_all_day() -> None:
    """All-day DTSTART (date only) returns T00:00:00 sentinel."""
    body = (
        "BEGIN:VCALENDAR\r\n"
        "DTSTART;VALUE=DATE:20260522\r\n"
        "DTEND;VALUE=DATE:20260523\r\n"
        "END:VCALENDAR\r\n"
    )
    start, end = _parse_ics_datetimes(body)
    assert start == "2026-05-22T00:00:00"
    assert end == "2026-05-23T00:00:00"


def test_parse_ics_datetimes_no_vcalendar() -> None:
    """Body without VCALENDAR returns (None, None)."""
    assert _parse_ics_datetimes("Hello, your appointment is confirmed.") == (None, None)


def test_extract_event_uses_ics_end_datetime() -> None:
    """When body contains VCALENDAR, end_datetime is extracted from DTEND."""
    body = (
        "Your appointment is confirmed.\r\n"
        "BEGIN:VCALENDAR\r\n"
        "DTSTART:20260522T140000Z\r\n"
        "DTEND:20260522T150000Z\r\n"
        "END:VCALENDAR\r\n"
    )
    email: dict[str, Any] = {
        "uid": "ics1",
        "subject": "Appointment confirmed",
        "sender_email": "noreply@clinic.com",
        "sender_name": "The Clinic",
        "date": "2026-05-20T10:00:00",
        "body_text": body,
    }
    result = extract_event(email)
    assert result is not None
    assert result.end_datetime is not None
    assert "15:00:00" in result.end_datetime


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


def test_extract_event_gcal_invite_subject_fallback() -> None:
    """GCal-style invite: date/time extracted from subject when body has none."""
    email: dict[str, Any] = {
        "uid": "gcalinvite1",
        "subject": "New event: Test @ Tue May 26, 2026 8pm - 9pm (BST) (Kitty)",
        "sender_email": "organizer@gmail.com",
        "sender_name": "Dan",
        "date": "2026-05-26T19:27:00",
        "body_text": "Dan has invited you to this event.\n",
    }
    result = extract_event(email)
    assert result is not None
    assert result.title == "Test"
    assert result.start_datetime is not None and "20:00:00" in result.start_datetime
    assert result.end_datetime is not None and "21:00:00" in result.end_datetime


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


def test_extract_calendar_change_subject_datetime() -> None:
    """start/end extracted from subject @ suffix when body has no When: field."""
    email: dict[str, Any] = {
        "uid": "gcal2",
        "subject": "Canceled event: Testing @ Tue May 26, 2026 9pm - 10pm (BST) (Kitty)",
        "sender_email": "organizer@gmail.com",
        "sender_name": "Dan",
        "date": "2026-05-26T20:30:00",
        "body_text": "This event has been cancelled.\n",
    }
    result = extract_calendar_change(email)
    assert result is not None
    assert result.event_title == "Testing"
    assert result.change_type == "cancel"
    assert result.start_datetime is not None and "21:00:00" in result.start_datetime
    assert result.end_datetime is not None and "22:00:00" in result.end_datetime
    assert result.calendar_name == "Kitty"
    assert result.changed_by == "Dan"


def test_extract_calendar_change_changed_by_fallback_email() -> None:
    """changed_by falls back to sender_email when no name or body field."""
    email: dict[str, Any] = {
        "uid": "gcal3",
        "subject": "New event: Standup @ Mon Jun 1, 2026 9am - 9:30am",
        "sender_email": "alice@example.com",
        "sender_name": None,
        "date": None,
        "body_text": "",
    }
    result = extract_calendar_change(email)
    assert result is not None
    assert result.changed_by == "alice@example.com"


def test_extract_calendar_from_at_suffix_skips_tz() -> None:
    """Timezone abbreviations skipped; calendar name is last non-tz paren."""
    from custom_components.email_events_ha.extractor import _extract_calendar_from_at_suffix
    assert _extract_calendar_from_at_suffix("Tue May 26, 2026 9pm (BST) (Kitty)") == "Kitty"
    assert _extract_calendar_from_at_suffix("Mon Jun 1 (UTC)") is None
    assert _extract_calendar_from_at_suffix(None) is None
