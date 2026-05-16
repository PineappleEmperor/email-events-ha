"""Constants for Email Events HA."""
from __future__ import annotations

DOMAIN = "email_events_ha"
PLATFORMS = ["sensor"]

CONF_EMAIL_HA_ENTRY_ID = "email_ha_entry_id"
CONF_SENDER_FILTER = "sender_filter"
CONF_SENDER_RULES = "sender_rules"
CONF_RULE_SENDER = "sender"
CONF_RULE_SCHEMA = "schema"

EMAIL_HA_DOMAIN = "email_ha"
EMAIL_HA_EVENT_NEW_EMAIL = "email_ha_new_email"
EMAIL_HA_SERVICE_QUERY = "query_emails"
EMAIL_HA_CONF_EMAIL = "email"

SCHEMA_GCAL = "gcal"
SCHEMA_GENERIC = "generic"
SCHEMA_SPECSAVERS = "specsavers"
SCHEMA_PHOREST = "phorest"

BUILTIN_SCHEMAS: dict[str, dict] = {
    SCHEMA_GCAL: {
        "label": "Google Calendar",
        "auto_senders": [
            "calendar-notification@google.com",
            "calendar-notifications@google.com",
        ],
        "ics_priority": True,
        "patterns": [],
    },
    SCHEMA_SPECSAVERS: {
        "label": "Specsavers",
        "auto_senders": [],
        "ics_priority": False,
        "patterns": [
            r"(?:is on|confirmed for)\s+(?:\w+\s+)?(?P<date>\d{1,2}\s+\w+\s+\d{4})\s+at\s+(?P<time>\d{1,2}:\d{2})",
            r"(?P<time>\d{1,2}:\d{2})\s*[-–]\s*(?:\w+,?\s+)?(?P<date>\d{1,2}\s+\w+\s+\d{4})",
        ],
    },
    SCHEMA_PHOREST: {
        "label": "Phorest (salon/clinic bookings)",
        "auto_senders": [],
        "ics_priority": False,
        "patterns": [
            r"seeing you on (?P<date>\d{1,2}\s+\w+\s+\d{4})",
        ],
    },
    SCHEMA_GENERIC: {
        "label": "Generic (fuzzy date/time extraction)",
        "auto_senders": [],
        "ics_priority": False,
        "patterns": [],
    },
}

KNOWN_SCHEMAS: dict[str, str] = {
    k: v["label"] for k, v in BUILTIN_SCHEMAS.items() if k != SCHEMA_GCAL
}

GCAL_NOTIFICATION_SENDERS: frozenset[str] = frozenset(
    s.lower() for s in BUILTIN_SCHEMAS[SCHEMA_GCAL]["auto_senders"]
)

SERVICE_CREATE_SCHEMA = "create_schema"
SERVICE_UPDATE_SCHEMA = "update_schema"
SERVICE_DELETE_SCHEMA = "delete_schema"
SERVICE_LIST_SCHEMAS = "list_schemas"
SERVICE_RELOAD_SCHEMAS = "reload_schemas"
SERVICE_RESET_STATS = "reset_stats"

SCHEMA_STORAGE_KEY = "email_events_ha.schemas"
STATS_STORAGE_KEY = "email_events_ha.stats"
SCHEMA_STORAGE_VERSION = 1
STATS_STORAGE_VERSION = 1

CHANGE_TYPE_NEW = "new"
CHANGE_TYPE_UPDATE = "update"
CHANGE_TYPE_CANCEL = "cancel"

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

ATTR_START_DATETIME = "start_datetime"
ATTR_END_DATETIME = "end_datetime"
ATTR_LOCATION = "location"
ATTR_ORGANIZER = "organizer"
ATTR_SOURCE_EMAIL = "source_email"
ATTR_RAW_SUBJECT = "raw_subject"
ATTR_UID = "uid"
ATTR_SENT_DATETIME = "sent_datetime"
ATTR_CONFIDENCE = "confidence"
ATTR_EXTRACTED_AT = "extracted_at"
ATTR_CHANGE_TYPE = "change_type"
ATTR_CALENDAR_NAME = "calendar_name"
ATTR_EVENT_TITLE = "event_title"
ATTR_CHANGED_BY = "changed_by"
ATTR_RECIPIENT_EMAIL = "recipient_email"
