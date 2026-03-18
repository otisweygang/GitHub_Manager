from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ClaudeConfig

log = logging.getLogger("bot.llm")

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def generate(
    intent: str,
    context: dict,
    fallback: str,
    claude_config: "ClaudeConfig | None" = None,
) -> str:
    """Always returns a string. Never raises. Never affects control flow.

    Claude failure → logs a warning and returns the fallback string.
    """
    if claude_config is None or not claude_config.enabled:
        return fallback
    try:
        client = _get_client()
        system = _build_system_prompt(claude_config)
        user_msg = _build_user_message(intent, context)
        message = client.messages.create(
            model=claude_config.model,
            max_tokens=claude_config.max_tokens,
            temperature=claude_config.temperature,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        log.warning("Claude unavailable (%s), using fallback template", exc)
        return fallback


def _build_system_prompt(cfg: "ClaudeConfig") -> str:
    rules = [
        "You are an automated GitHub bot assistant.",
        "Output only the requested text — no surrounding explanation, no metadata.",
    ]
    if cfg.style.no_preamble:
        rules.append('Do not open with affirmations ("Sure", "Of course", "Here\'s", etc.).')
    if cfg.style.no_emojis:
        rules.append("Do not use emojis.")
    if cfg.style.concise:
        rules.append("Be concise. No padding, no filler phrases, no redundant sentences.")
    if cfg.style.tone == "professional":
        rules.append("Tone: professional and direct.")

    return " ".join(rules)


def _build_user_message(intent: str, context: dict) -> str:
    ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
    return f"Task: {intent}\n\nContext:\n{ctx_lines}"
