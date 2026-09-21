from __future__ import annotations

import os
from typing import Any

CODE_MODEL_DEFAULT = "openai/gpt-oss-120b"
OPERATIONS_MODEL_DEFAULT = "openai/gpt-oss-20b"


def create_groq_model(
    role: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Any:
    """Create a Groq LangChain model for the requested task role."""
    from tools.base import ToolError

    if role == "code":
        model_name = model or os.getenv("GROQ_CODE_MODEL") or os.getenv("GROQ_FREE_MODEL") or CODE_MODEL_DEFAULT
    elif role == "operations":
        model_name = model or os.getenv("GROQ_OPERATIONS_MODEL") or OPERATIONS_MODEL_DEFAULT
    else:
        raise ToolError(f"Unsupported Groq model role: {role}")

    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise ToolError("GROQ_API_KEY is required for Groq model calls.")

    from langchain.chat_models import init_chat_model

    kwargs: dict[str, Any] = {
        "model": model_name,
        "model_provider": "groq",
        "temperature": 0,
        "api_key": key,
        "max_tokens": max_tokens or int(os.getenv("LLM_MAX_TOKENS", "4000")),
    }

    # gpt-oss models are reasoning models. Keep the chain-of-thought out of
    # `content` so JSON parsing stays reliable, and keep it short so the free
    # tier's 8k tokens-per-minute budget is not spent on reasoning.
    if "gpt-oss" in model_name:
        kwargs["reasoning_format"] = os.getenv("GROQ_REASONING_FORMAT", "hidden")
        kwargs["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "medium")

    try:
        return init_chat_model(**kwargs)
    except TypeError:
        # Older langchain-groq does not expose the reasoning_* parameters.
        for key_name in ("reasoning_format", "reasoning_effort"):
            kwargs.pop(key_name, None)
        return init_chat_model(**kwargs)
