from __future__ import annotations

import os
from typing import Any

CODE_MODEL_DEFAULT = "openai/gpt-oss-120b"
OPERATIONS_MODEL_DEFAULT = "openai/gpt-oss-20b"


def create_groq_model(role: str, *, api_key: str | None = None, model: str | None = None) -> Any:
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

    return init_chat_model(
        model=model_name,
        model_provider="groq",
        temperature=0,
        api_key=key,
    )