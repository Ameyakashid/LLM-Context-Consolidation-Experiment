"""Nanobot-ai tool for text-to-speech voice message delivery.

Exposes a SpeakTool that the LLM can call to send a voice message.
Synthesizes text via Kokoro TTS, converts to OGG/Opus, and sends
via the existing MessageTool infrastructure.

Registration: call register_voice_tools(registry, message_tool) at startup.
"""

import asyncio
import logging

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import (
    NumberSchema,
    StringSchema,
    tool_parameters_schema,
)

from tts_engine import DEFAULT_LANG, DEFAULT_SPEED, DEFAULT_VOICE, synthesize_speech
from voice_delivery import cleanup_temp_file, convert_wav_to_ogg, save_temp_ogg

log = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 500


@tool_parameters(
    tool_parameters_schema(
        text=StringSchema("The text to speak aloud as a voice message"),
        voice=StringSchema(
            "Kokoro voice name (e.g. 'af_heart', 'am_adam')",
            nullable=True,
        ),
        speed=NumberSchema(
            description="Speech speed multiplier (1.0 = normal, 1.2 = faster)",
            minimum=0.5,
            maximum=3.0,
            nullable=True,
        ),
        required=["text"],
    )
)
class SpeakTool(Tool):
    """Tool to send a voice message by synthesizing text to speech."""

    def __init__(self, message_tool: Tool) -> None:
        self._message_tool = message_tool

    @property
    def name(self) -> str:
        return "speak"

    @property
    def description(self) -> str:
        return (
            "Send a voice message by converting text to speech. "
            "Synthesizes the text using Kokoro TTS and sends it as "
            f"a Telegram voice message. Maximum {MAX_TEXT_LENGTH} characters."
        )

    async def execute(
        self,
        text: str,
        voice: str | None = None,
        speed: float | None = None,
    ) -> str:
        if not text.strip():
            return "Error: Cannot speak empty text."

        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH]

        resolved_voice = voice if voice is not None else DEFAULT_VOICE
        resolved_speed = speed if speed is not None else DEFAULT_SPEED

        try:
            wav_bytes = await asyncio.to_thread(
                synthesize_speech,
                text=text,
                voice=resolved_voice,
                speed=resolved_speed,
                lang=DEFAULT_LANG,
            )
        except FileNotFoundError as exc:
            return f"Error: TTS engine unavailable — {exc}"
        except ValueError as exc:
            return f"Error: {exc}"

        try:
            ogg_bytes = convert_wav_to_ogg(wav_bytes)
        except Exception as exc:
            return f"Error: Audio conversion failed — {exc}"

        ogg_path = save_temp_ogg(ogg_bytes)
        try:
            result = await self._message_tool.execute(
                content="",
                media=[str(ogg_path)],
            )
        finally:
            cleanup_temp_file(ogg_path)

        return result


def register_voice_tools(registry: ToolRegistry, message_tool: Tool) -> int:
    """Register voice tools into a ToolRegistry.

    Args:
        registry: The tool registry to register into.
        message_tool: The MessageTool instance for sending voice messages.

    Returns the number of tools registered.
    """
    tools: list[Tool] = [SpeakTool(message_tool=message_tool)]
    for tool in tools:
        registry.register(tool)
    count = len(tools)
    log.info("Registered %d voice tool: speak", count)
    return count
