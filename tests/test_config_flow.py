"""Tests for config flow and options flow."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.email_events_ha.config_flow import (
    EmailEventsHAConfigFlow,
    EmailEventsHAOptionsFlow,
)
from custom_components.email_events_ha.const import (
    CONF_EMAIL_HA_ENTRY_ID,
    CONF_RULE_SCHEMA,
    CONF_RULE_SENDER,
    CONF_SENDER_FILTER,
    CONF_SENDER_RULES,
    EMAIL_HA_DOMAIN,
    SCHEMA_SPECSAVERS,
)

from .conftest import MOCK_EMAIL_ADDRESS, MOCK_EMAIL_HA_ENTRY_ID


def _make_hass(email_ha_entries: list[MagicMock] | None = None) -> MagicMock:
    """Return a minimal hass mock with email_ha config entries."""
    hass = MagicMock()
    entries = email_ha_entries if email_ha_entries is not None else [
        MagicMock(entry_id=MOCK_EMAIL_HA_ENTRY_ID, data={"email": MOCK_EMAIL_ADDRESS}, title=MOCK_EMAIL_ADDRESS)
    ]
    hass.config_entries.async_entries = MagicMock(
        side_effect=lambda domain: entries if domain == EMAIL_HA_DOMAIN else []
    )
    return hass


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_flow_aborts_when_no_email_ha() -> None:
    """Flow aborts when no email_ha entries exist."""
    flow = EmailEventsHAConfigFlow()
    flow.hass = _make_hass(email_ha_entries=[])
    result = await flow.async_step_user()
    assert result["type"] == "abort"
    assert result["reason"] == "no_email_ha_entries"


@pytest.mark.asyncio
async def test_config_flow_creates_entry() -> None:
    """Valid submission creates a config entry."""
    flow = EmailEventsHAConfigFlow()
    flow.hass = _make_hass()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry", "title": MOCK_EMAIL_ADDRESS, "data": {}})

    user_input = {
        CONF_EMAIL_HA_ENTRY_ID: MOCK_EMAIL_HA_ENTRY_ID,
        CONF_SENDER_FILTER: "",
    }
    result = await flow.async_step_user(user_input=user_input)
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_config_flow_shows_form_without_input() -> None:
    """Step without input returns a form."""
    flow = EmailEventsHAConfigFlow()
    flow.hass = _make_hass()
    result = await flow.async_step_user()
    assert result["type"] == "form"
    assert result["step_id"] == "user"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


def _make_options_flow(
    sender_filter: str = "",
    sender_rules: list[dict[str, str]] | None = None,
) -> EmailEventsHAOptionsFlow:
    """Build an options flow with preset state."""
    entry = MagicMock()
    entry.data = {CONF_SENDER_FILTER: sender_filter}
    entry.options = {
        CONF_SENDER_FILTER: sender_filter,
        CONF_SENDER_RULES: sender_rules or [],
    }
    flow = EmailEventsHAOptionsFlow(entry)
    flow.async_create_entry = MagicMock(
        side_effect=lambda title, data: {"type": "create_entry", "data": data}
    )
    flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    return flow


@pytest.mark.asyncio
async def test_options_flow_save() -> None:
    """Edit filter step saves options immediately on submit."""
    flow = _make_options_flow(sender_filter="old@example.com")
    result = await flow.async_step_edit_filter(user_input={CONF_SENDER_FILTER: "new@example.com"})
    assert result["type"] == "create_entry"
    assert result["data"][CONF_SENDER_FILTER] == "new@example.com"


@pytest.mark.asyncio
async def test_options_flow_edit_filter() -> None:
    """Edit filter step updates pending filter."""
    flow = _make_options_flow(sender_filter="old@example.com")
    await flow.async_step_edit_filter(user_input={CONF_SENDER_FILTER: "new@example.com"})
    assert flow._pending_filter == "new@example.com"


@pytest.mark.asyncio
async def test_options_flow_add_rule() -> None:
    """Add rule action then submitting adds rule to pending list."""
    flow = _make_options_flow()

    # Trigger add_rule step
    await flow.async_step_init(user_input={"action": "add_rule"})

    # Submit the add_rule form
    await flow.async_step_add_rule(
        user_input={CONF_RULE_SENDER: "noreply@specsavers.com", CONF_RULE_SCHEMA: SCHEMA_SPECSAVERS}
    )

    assert len(flow._pending_rules) == 1
    assert flow._pending_rules[0][CONF_RULE_SENDER] == "noreply@specsavers.com"
    assert flow._pending_rules[0][CONF_RULE_SCHEMA] == SCHEMA_SPECSAVERS


@pytest.mark.asyncio
async def test_options_flow_add_rule_deduplicates() -> None:
    """Adding a rule for an existing sender replaces it."""
    flow = _make_options_flow(
        sender_rules=[{CONF_RULE_SENDER: "noreply@specsavers.com", CONF_RULE_SCHEMA: "generic"}]
    )

    await flow.async_step_add_rule(
        user_input={CONF_RULE_SENDER: "noreply@specsavers.com", CONF_RULE_SCHEMA: SCHEMA_SPECSAVERS}
    )

    assert len(flow._pending_rules) == 1
    assert flow._pending_rules[0][CONF_RULE_SCHEMA] == SCHEMA_SPECSAVERS


@pytest.mark.asyncio
async def test_options_flow_remove_rule() -> None:
    """Remove rule step removes the selected rule."""
    flow = _make_options_flow(
        sender_rules=[
            {CONF_RULE_SENDER: "a@example.com", CONF_RULE_SCHEMA: "generic"},
            {CONF_RULE_SENDER: "b@example.com", CONF_RULE_SCHEMA: SCHEMA_SPECSAVERS},
        ]
    )

    await flow.async_step_remove_rule(user_input={"rule_index": "0"})

    assert len(flow._pending_rules) == 1
    assert flow._pending_rules[0][CONF_RULE_SENDER] == "b@example.com"


@pytest.mark.asyncio
async def test_options_flow_filter_preserved_across_add() -> None:
    """Filter set via edit_filter is preserved when navigating to add_rule."""
    flow = _make_options_flow()

    await flow.async_step_edit_filter(user_input={CONF_SENDER_FILTER: "kept@example.com"})
    await flow.async_step_init(user_input={"action": "add_rule"})

    assert flow._pending_filter == "kept@example.com"


@pytest.mark.asyncio
async def test_options_flow_add_rule_empty_sender_error() -> None:
    """Empty sender returns an error."""
    flow = _make_options_flow()
    result = await flow.async_step_add_rule(
        user_input={CONF_RULE_SENDER: "  ", CONF_RULE_SCHEMA: "generic"}
    )
    assert result["type"] == "form"
    assert "errors" in result
    assert result["errors"].get(CONF_RULE_SENDER) == "empty_sender"
