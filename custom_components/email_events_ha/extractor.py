"""Email body parsing for event and Google Calendar change extraction."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re
from typing import Any

from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError

from .const import (
    BUILTIN_SCHEMAS,
    CHANGE_TYPE_CANCEL,
    CHANGE_TYPE_NEW,
    CHANGE_TYPE_UPDATE,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    GCAL_NOTIFICATION_SENDERS,
    SCHEMA_GENERIC,
)

_LOGGER = logging.getLogger(__name__)

_ICS_DTSTART_RE = re.compile(r"^DTSTART(?:;[^:]+)?:(.+)$", re.MULTILINE)
_ICS_DTEND_RE = re.compile(r"^DTEND(?:;[^:]+)?:(.+)$", re.MULTILINE)

_YEAR_RE = re.compile(r"\b20\d{2}\b")
_TIME_RANGE_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_AMPM_RANGE_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*[-–]\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
_AMPM_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}[0-9][0-9A-Z]?\s*[0-9][A-Z]{2}\b")

_AT_PLACE_RE = re.compile(
    r"\bat\s+([A-Z][A-Za-z0-9&'\-\s]{2,49})(?=\s*(?:\n|$|,|\.))",
    re.MULTILINE,
)
_AT_PLACE_REJECT = re.compile(r"^\d{1,2}:\d{2}|^(?:least|all|this|that|the|a|an)\b", re.IGNORECASE)

_GCAL_SUBJECT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?:New event|Invitation):\s+(.+?)(?:\s+@\s+.+)?$", re.IGNORECASE), CHANGE_TYPE_NEW),
    (re.compile(r"^Updated invitation:\s+(.+?)(?:\s+@\s+.+)?$", re.IGNORECASE), CHANGE_TYPE_UPDATE),
    (re.compile(r"^(?:Cancelled|Canceled) event:\s+(.+?)(?:\s+@\s+.+)?$", re.IGNORECASE), CHANGE_TYPE_CANCEL),
    (re.compile(r"^(?:Updated|Changed):\s+(.+?)(?:\s+@\s+.+)?$", re.IGNORECASE), CHANGE_TYPE_UPDATE),
    (re.compile(r"^Accepted:\s+(.+?)(?:\s+@\s+.+)?$", re.IGNORECASE), CHANGE_TYPE_NEW),
]

_GENERIC_TIME_FIRST_RE = re.compile(
    r"^(?P<time>\d{1,2}:\d{2})\s*[-–]\s*(?:\w+,?\s+)?(?P<date>\d{1,2}\s+\w+\s+\d{4})\s*$",
    re.IGNORECASE,
)

_SUBJECT_STRIP_PREFIX_RE = re.compile(
    r"^(?:booking\s+confirmation\s+for\s+\w+\s+|"
    r"appointment\s+confirmation\s+for\s+\w+\s+|"
    r"(?:new\s+event|invitation|updated\s+invitation|cancelled\s+event|canceled\s+event|accepted):\s+|"
    r"\w+,\s+your\s+|"
    r"your\s+)",
    re.IGNORECASE,
)
_SUBJECT_STRIP_SUFFIX_RE = re.compile(
    r"\s+(?:is\s+coming\s+up|reminder|@\s+.+)\s*$",
    re.IGNORECASE,
)


@dataclass
class DetectedEvent:
    """Parsed event from a general booking/appointment email."""

    title: str
    start_datetime: str | None
    end_datetime: str | None
    location: str | None
    organizer: str | None
    source_email: str
    raw_subject: str
    uid: str
    sent_datetime: str | None
    confidence: str
    extracted_at: str


@dataclass
class CalendarChange:
    """Parsed Google Calendar change notification."""

    event_title: str
    change_type: str
    start_datetime: str | None
    organizer: str | None
    calendar_name: str | None
    changed_by: str | None
    recipient_email: str | None
    source_email: str
    uid: str
    sent_datetime: str | None
    extracted_at: str


def is_gcal_notification(sender_email: str) -> bool:
    """Return True if sender is a known Google Calendar notification address."""
    return sender_email.lower() in GCAL_NOTIFICATION_SENDERS


def is_gcal_subject(subject: str) -> bool:
    """Return True if subject matches a known Google Calendar notification pattern."""
    s = subject.strip()
    return any(p.match(s) for p, _ in _GCAL_SUBJECT_PATTERNS)


def extract_event(
    email_data: dict[str, Any],
    schema: str = SCHEMA_GENERIC,
    patterns: list[str] | None = None,
) -> DetectedEvent | None:
    """Extract event details from a general booking/appointment email body."""
    subject: str = email_data.get("subject") or ""
    body: str = email_data.get("body_text") or ""
    sender_email: str = email_data.get("sender_email") or ""
    uid: str = email_data.get("uid") or ""
    sent_datetime: str | None = email_data.get("date")
    extracted_at = datetime.now(timezone.utc).isoformat()

    title = _clean_subject(subject)

    ics_start, ics_end = _parse_ics_datetimes(body)

    resolved_patterns = patterns if patterns is not None else BUILTIN_SCHEMAS.get(schema, {}).get("patterns", [])

    schema_result: tuple[str | None, str | None, str | None] = (None, None, None)
    if resolved_patterns:
        schema_result = _run_named_group_patterns(body, resolved_patterns)

    if schema_result[0] is not None:
        start_dt, end_dt, schema_location = schema_result
        end_dt = end_dt or ics_end
        location = schema_location or _extract_location(body)
    elif ics_start:
        start_dt, end_dt = ics_start, ics_end
        location = _extract_location(body)
    else:
        start_dt, end_dt = _extract_datetimes(body)
        if not start_dt:
            start_dt, end_dt = _extract_datetimes(subject)
        location = _extract_location(body)

    if not start_dt:
        _LOGGER.debug("No date found in email uid=%s subject=%r", uid, subject)
        return None

    has_time = not start_dt.endswith("T00:00:00")
    if has_time and location:
        confidence = CONFIDENCE_HIGH
    elif has_time or location:
        confidence = CONFIDENCE_MEDIUM
    else:
        confidence = CONFIDENCE_LOW

    return DetectedEvent(
        title=title,
        start_datetime=start_dt,
        end_datetime=end_dt,
        location=location,
        organizer=email_data.get("sender_name") or sender_email,
        source_email=sender_email,
        raw_subject=subject,
        uid=uid,
        sent_datetime=sent_datetime,
        confidence=confidence,
        extracted_at=extracted_at,
    )


def extract_calendar_change(email_data: dict[str, Any]) -> CalendarChange | None:
    """Extract change info from a Google Calendar notification email."""
    subject: str = email_data.get("subject") or ""
    body: str = email_data.get("body_text") or ""
    sender_email: str = email_data.get("sender_email") or ""
    uid: str = email_data.get("uid") or ""
    sent_datetime: str | None = email_data.get("date")
    extracted_at = datetime.now(timezone.utc).isoformat()

    event_title: str | None = None
    change_type: str | None = None

    for pattern, ctype in _GCAL_SUBJECT_PATTERNS:
        m = pattern.match(subject.strip())
        if m:
            event_title = m.group(1).strip()
            change_type = ctype
            break

    if not event_title or not change_type:
        _LOGGER.debug("No GCal pattern matched subject=%r", subject)
        return None

    start_dt = _parse_gcal_when_field(body)
    organizer = _parse_gcal_field(body, "organizer") or _parse_gcal_field(body, "who")
    calendar_name = _parse_gcal_field(body, "calendar")
    changed_by = (
        _parse_gcal_field(body, "changed by")
        or _parse_gcal_field(body, "modified by")
        or _parse_gcal_field(body, "updated by")
    )

    return CalendarChange(
        event_title=event_title,
        change_type=change_type,
        start_datetime=start_dt,
        organizer=organizer,
        calendar_name=calendar_name,
        changed_by=changed_by,
        recipient_email=None,
        source_email=sender_email,
        uid=uid,
        sent_datetime=sent_datetime,
        extracted_at=extracted_at,
    )


def _parse_ics_datetimes(body: str) -> tuple[str | None, str | None]:
    """Extract DTSTART/DTEND from an embedded VCALENDAR block in body text."""
    if "BEGIN:VCALENDAR" not in body:
        return None, None

    def _ics_dt(raw: str) -> str | None:
        val = raw.strip()
        try:
            if "T" in val:
                naive = datetime.strptime(val.rstrip("Z"), "%Y%m%dT%H%M%S")
                if val.endswith("Z"):
                    return naive.replace(tzinfo=timezone.utc).isoformat()
                return naive.isoformat()
            return datetime.strptime(val, "%Y%m%d").date().isoformat() + "T00:00:00"
        except ValueError:
            return None

    start_m = _ICS_DTSTART_RE.search(body)
    end_m = _ICS_DTEND_RE.search(body)
    return _ics_dt(start_m.group(1)) if start_m else None, _ics_dt(end_m.group(1)) if end_m else None


def _clean_subject(subject: str) -> str:
    """Strip common booking prefixes/suffixes from a subject line."""
    title = _SUBJECT_STRIP_PREFIX_RE.sub("", subject).strip()
    title = _SUBJECT_STRIP_SUFFIX_RE.sub("", title).strip()
    return title or subject


def _extract_datetimes(body: str) -> tuple[str | None, str | None]:
    """Scan body lines for date/time patterns; return (start_iso, end_iso)."""
    current_year = datetime.now(timezone.utc).year
    best_start: str | None = None
    best_end: str | None = None
    best_score = 0

    for line in body.splitlines():
        line = line.strip()
        if not line or len(line) > 200:
            continue
        if not _YEAR_RE.search(line):
            continue

        clean = _URL_RE.sub("", line).strip()
        if len(clean) < 5:
            continue

        td_m = _GENERIC_TIME_FIRST_RE.match(clean)
        ampm_range_m = _AMPM_RANGE_RE.search(clean) if not td_m else None

        if td_m:
            try:
                dt = dateutil_parser.parse(
                    f"{td_m.group('date')} {td_m.group('time')}", dayfirst=True
                )
            except (ParserError, ValueError):
                continue
        elif ampm_range_m:
            date_with_start = clean[: ampm_range_m.end(3)]
            try:
                dt = dateutil_parser.parse(date_with_start, dayfirst=True, fuzzy=True)
            except (ParserError, OverflowError, ValueError):
                continue
        else:
            try:
                dt = dateutil_parser.parse(clean, dayfirst=True, fuzzy=True)
            except (ParserError, OverflowError, ValueError):
                continue

        if abs(dt.year - current_year) > 5:
            continue

        has_time = bool(_TIME_RE.search(clean)) or bool(ampm_range_m) or bool(_AMPM_TIME_RE.search(clean))
        score = 2 if has_time else 1

        if score <= best_score:
            continue

        best_score = score
        if has_time:
            range_m = _TIME_RANGE_RE.search(clean)
            if range_m:
                try:
                    sh, sm = map(int, range_m.group(1).split(":"))
                    eh, em = map(int, range_m.group(2).split(":"))
                    best_start = dt.replace(hour=sh, minute=sm, microsecond=0).isoformat()
                    best_end = dt.replace(hour=eh, minute=em, microsecond=0).isoformat()
                except ValueError:
                    best_start = dt.replace(microsecond=0).isoformat()
                    best_end = None
            elif ampm_range_m:
                end_time_str = ampm_range_m.group(4)
                if ampm_range_m.group(5):
                    end_time_str += ":" + ampm_range_m.group(5)
                end_time_str += ampm_range_m.group(6)
                try:
                    end_dt = dateutil_parser.parse(
                        f"{dt.date().isoformat()} {end_time_str}", dayfirst=True
                    )
                    best_start = dt.replace(microsecond=0).isoformat()
                    best_end = end_dt.replace(microsecond=0).isoformat()
                except (ParserError, ValueError):
                    best_start = dt.replace(microsecond=0).isoformat()
                    best_end = None
            else:
                best_start = dt.replace(microsecond=0).isoformat()
                best_end = None
        else:
            best_start = dt.date().isoformat() + "T00:00:00"
            best_end = None

    return best_start, best_end


def _extract_location(body: str) -> str | None:
    """Extract location using 'at [Place]' pattern or UK postcode block."""
    for m in _AT_PLACE_RE.finditer(body):
        candidate = m.group(1).strip()
        if _AT_PLACE_REJECT.match(candidate):
            continue
        if len(candidate) > 3:
            return candidate

    postcode_m = _UK_POSTCODE_RE.search(body)
    if postcode_m:
        start = max(0, postcode_m.start() - 150)
        block = body[start : postcode_m.end()]
        lines = [
            ln.strip()
            for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith("http")
        ]
        if lines:
            return ", ".join(lines[-3:])

    return None


def _parse_gcal_field(body: str, field: str) -> str | None:
    """Parse a labelled field from a GCal notification body (e.g. 'When: ...')."""
    pattern = re.compile(rf"^{re.escape(field)}\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(body)
    return m.group(1).strip() if m else None


def _parse_gcal_when_field(body: str) -> str | None:
    """Parse and convert the 'When:' field from a GCal notification body."""
    when = _parse_gcal_field(body, "when")
    if not when:
        return None
    try:
        dt = dateutil_parser.parse(when, dayfirst=True, fuzzy=True)
        return dt.replace(microsecond=0).isoformat()
    except (ParserError, ValueError, OverflowError):
        return when


def _run_named_group_patterns(
    body: str, patterns: list[str]
) -> tuple[str | None, str | None, str | None]:
    """Run named-group regex patterns against body; return (start_iso, end_iso, location)."""
    for pattern_str in patterns:
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.MULTILINE)
        except re.error:
            _LOGGER.warning("Invalid regex pattern: %r", pattern_str)
            continue
        for line in body.splitlines():
            m = pattern.search(line.strip())
            if not m:
                continue
            gd = m.groupdict()
            date_str: str | None = gd.get("date")
            time_str: str | None = gd.get("time")
            end_time_str: str | None = gd.get("end_time")
            location: str | None = gd.get("location") or None
            if not date_str:
                continue
            try:
                if time_str:
                    dt = dateutil_parser.parse(f"{date_str} {time_str}", dayfirst=True)
                    start_iso = dt.replace(microsecond=0).isoformat()
                    if end_time_str:
                        h, mn = map(int, end_time_str.split(":"))
                        end_iso: str | None = dt.replace(hour=h, minute=mn, microsecond=0).isoformat()
                    else:
                        end_iso = None
                else:
                    dt = dateutil_parser.parse(date_str, dayfirst=True)
                    start_iso = dt.date().isoformat() + "T00:00:00"
                    end_iso = None
            except (ParserError, ValueError):
                continue
            else:
                return start_iso, end_iso, location
    return None, None, None
