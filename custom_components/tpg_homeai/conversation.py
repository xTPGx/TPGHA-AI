"""Conversation agent that forwards Home Assistant Assist input to TPG HomeAI.

Registers a ConversationEntity so it can be selected as the Assist agent. Each
utterance is POSTed to the TPG HomeAI server's /command endpoint, and the
server's response text is spoken back to the user.
"""
from __future__ import annotations

import logging

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import ulid

from . import TPGHomeAIClient, TPGHomeAIError
from .const import (
    CONF_ASSISTANT_ID,
    CONF_USER_ID,
    DATA_CLIENT,
    DEFAULT_ASSISTANT_ID,
    DEFAULT_USER_ID,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the conversation entity for a config entry."""
    client: TPGHomeAIClient = hass.data[DOMAIN][entry.entry_id][DATA_CLIENT]
    async_add_entities([TPGHomeAIConversationAgent(entry, client)])


class TPGHomeAIConversationAgent(conversation.ConversationEntity):
    """A conversation agent backed by the TPG HomeAI Orchestrator server."""

    _attr_has_entity_name = True
    _attr_name = "TPG HomeAI"

    def __init__(self, entry: ConfigEntry, client: TPGHomeAIClient) -> None:
        self._entry = entry
        self._client = client
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=DEVICE_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str] | str:
        # The server handles language understanding; accept everything.
        return MATCH_ALL

    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        conversation_id = user_input.conversation_id or ulid.ulid_now()
        assistant_id = self._entry.options.get(CONF_ASSISTANT_ID, DEFAULT_ASSISTANT_ID)
        user_id = (
            (user_input.context.user_id if user_input.context else None)
            or self._entry.options.get(CONF_USER_ID, DEFAULT_USER_ID)
        )

        _LOGGER.debug(
            "Forwarding Assist input to TPG HomeAI (assistant=%s, conversation=%s)",
            assistant_id,
            conversation_id,
        )

        try:
            result = await self._client.async_command(
                text=user_input.text,
                assistant_id=assistant_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except TPGHomeAIError as err:
            return self._error_result(
                user_input,
                conversation_id,
                f"I couldn't reach the TPG HomeAI server. {err}",
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error talking to TPG HomeAI server")
            return self._error_result(
                user_input,
                conversation_id,
                "Something went wrong talking to the TPG HomeAI server.",
            )

        speech = result.get("message") or "Done."
        if result.get("requires_confirmation"):
            # Surface the confirmation prompt; confirmation is completed in the
            # TPG HomeAI UI or via the test_command service for the MVP.
            speech = result.get("confirmation_message") or speech

        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(speech)
        return conversation.ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )

    def _error_result(
        self,
        user_input: conversation.ConversationInput,
        conversation_id: str,
        message: str,
    ) -> conversation.ConversationResult:
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_error(
            intent.IntentResponseErrorCode.FAILED_TO_HANDLE, message
        )
        return conversation.ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )
