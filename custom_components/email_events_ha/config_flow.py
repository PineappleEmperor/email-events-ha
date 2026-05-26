"""Config flow for Email Events HA."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_EMAIL_HA_ENTRY_ID,
    CONF_EMAIL_NAMES,
    CONF_NAME_DISPLAY,
    CONF_NAME_EMAIL,
    CONF_RULE_SCHEMA,
    CONF_RULE_SENDER,
    CONF_SENDER_FILTER,
    CONF_SENDER_RULES,
    DOMAIN,
    EMAIL_HA_CONF_EMAIL,
    EMAIL_HA_DOMAIN,
    KNOWN_SCHEMAS,
)

_LOGGER = logging.getLogger(__name__)

_ACTION_SAVE = "save"
_ACTION_ADD = "add_rule"
_ACTION_REMOVE = "remove_rule"
_ACTION_ADD_NAME = "add_name"
_ACTION_REMOVE_NAME = "remove_name"


def _email_ha_entry_options(hass: HomeAssistant) -> dict[str, str]:
    """Return {entry_id: display_label} for all email_ha config entries."""
    return {
        entry.entry_id: entry.data.get(EMAIL_HA_CONF_EMAIL, entry.title)
        for entry in hass.config_entries.async_entries(EMAIL_HA_DOMAIN)
    }


class EmailEventsHAConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Email Events HA."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EmailEventsHAOptionsFlow:
        """Return the options flow handler."""
        return EmailEventsHAOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial config step."""
        email_ha_options = _email_ha_entry_options(self.hass)

        if not email_ha_options:
            return self.async_abort(reason="no_email_ha_entries")

        errors: dict[str, str] = {}

        if user_input is not None:
            entry_id: str = user_input[CONF_EMAIL_HA_ENTRY_ID]
            email_address = email_ha_options.get(entry_id, entry_id)
            return self.async_create_entry(
                title=email_address,
                data=user_input,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL_HA_ENTRY_ID): vol.In(email_ha_options),
                vol.Optional(CONF_SENDER_FILTER, default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={},
        )


class EmailEventsHAOptionsFlow(OptionsFlow):
    """Options flow: manage sender filter and per-sender schema rules."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Load current options into pending state."""
        self._pending_filter: str = config_entry.options.get(
            CONF_SENDER_FILTER,
            config_entry.data.get(CONF_SENDER_FILTER, ""),
        )
        self._pending_rules: list[dict[str, str]] = list(
            config_entry.options.get(CONF_SENDER_RULES, [])
        )
        self._pending_names: list[dict[str, str]] = list(
            config_entry.options.get(CONF_EMAIL_NAMES, [])
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show current settings and action menu."""
        if user_input is not None:
            self._pending_filter = user_input.get(CONF_SENDER_FILTER, self._pending_filter)
            action = user_input.get("action", _ACTION_SAVE)
            if action == _ACTION_ADD:
                return await self.async_step_add_rule()
            if action == _ACTION_REMOVE and self._pending_rules:
                return await self.async_step_remove_rule()
            if action == _ACTION_ADD_NAME:
                return await self.async_step_add_name()
            if action == _ACTION_REMOVE_NAME and self._pending_names:
                return await self.async_step_remove_name()
            return self.async_create_entry(
                title="",
                data={
                    CONF_SENDER_FILTER: self._pending_filter,
                    CONF_SENDER_RULES: self._pending_rules,
                    CONF_EMAIL_NAMES: self._pending_names,
                },
            )

        rules_desc = "\n".join(
            f"• {r[CONF_RULE_SENDER]} → {r[CONF_RULE_SCHEMA]}"
            for r in self._pending_rules
        ) or "None configured"

        names_desc = "\n".join(
            f"• {n[CONF_NAME_EMAIL]} → {n[CONF_NAME_DISPLAY]}"
            for n in self._pending_names
        ) or "None configured"

        actions = {
            _ACTION_SAVE: "Save changes",
            _ACTION_ADD: "Add sender rule",
            _ACTION_ADD_NAME: "Add email name mapping",
        }
        if self._pending_rules:
            actions[_ACTION_REMOVE] = "Remove a sender rule"
        if self._pending_names:
            actions[_ACTION_REMOVE_NAME] = "Remove a name mapping"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SENDER_FILTER, default=self._pending_filter): str,
                    vol.Required("action", default=_ACTION_SAVE): vol.In(actions),
                }
            ),
            description_placeholders={"rules": rules_desc, "names": names_desc},
        )

    async def async_step_add_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new sender → schema rule."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sender = user_input[CONF_RULE_SENDER].strip().lower()
            if not sender:
                errors[CONF_RULE_SENDER] = "empty_sender"
            else:
                # Replace existing rule for same sender if present
                self._pending_rules = [
                    r for r in self._pending_rules if r.get(CONF_RULE_SENDER) != sender
                ]
                self._pending_rules.append(
                    {CONF_RULE_SENDER: sender, CONF_RULE_SCHEMA: user_input[CONF_RULE_SCHEMA]}
                )
                return await self.async_step_init()

        return self.async_show_form(
            step_id="add_rule",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RULE_SENDER): str,
                    vol.Required(CONF_RULE_SCHEMA, default=list(KNOWN_SCHEMAS)[0]): vol.In(
                        KNOWN_SCHEMAS
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an existing sender rule."""
        if not self._pending_rules:
            return await self.async_step_init()

        if user_input is not None:
            idx = int(user_input["rule_index"])
            self._pending_rules.pop(idx)
            return await self.async_step_init()

        rule_options = {
            str(i): f"{r[CONF_RULE_SENDER]} → {r[CONF_RULE_SCHEMA]}"
            for i, r in enumerate(self._pending_rules)
        }

        return self.async_show_form(
            step_id="remove_rule",
            data_schema=vol.Schema(
                {vol.Required("rule_index"): vol.In(rule_options)}
            ),
        )

    async def async_step_add_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add or update an email → display name mapping."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_NAME_EMAIL].strip().lower()
            name = user_input[CONF_NAME_DISPLAY].strip()
            if not email:
                errors[CONF_NAME_EMAIL] = "empty_email"
            elif not name:
                errors[CONF_NAME_DISPLAY] = "empty_name"
            else:
                self._pending_names = [
                    n for n in self._pending_names if n.get(CONF_NAME_EMAIL) != email
                ]
                self._pending_names.append({CONF_NAME_EMAIL: email, CONF_NAME_DISPLAY: name})
                return await self.async_step_init()

        return self.async_show_form(
            step_id="add_name",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME_EMAIL): str,
                    vol.Required(CONF_NAME_DISPLAY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_remove_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove an existing email name mapping."""
        if not self._pending_names:
            return await self.async_step_init()

        if user_input is not None:
            idx = int(user_input["name_index"])
            self._pending_names.pop(idx)
            return await self.async_step_init()

        name_options = {
            str(i): f"{n[CONF_NAME_EMAIL]} → {n[CONF_NAME_DISPLAY]}"
            for i, n in enumerate(self._pending_names)
        }

        return self.async_show_form(
            step_id="remove_name",
            data_schema=vol.Schema(
                {vol.Required("name_index"): vol.In(name_options)}
            ),
        )
