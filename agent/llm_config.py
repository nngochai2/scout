"""Shared LiteLLM provider/model/api-key resolution.

Every call site that invokes ``litellm.completion()`` directly (Triage,
Evaluate, MCP tool-call dispatch) needs the same LLM_BASE_URL / provider
prefix / api-key lookup. Centralised here so it's defined once.
"""
import os

_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
}


def resolve(model: str) -> tuple[str, dict]:
    """Return (model, extra_kwargs) ready to splat into litellm.completion(**extra)."""
    extra: dict = {}
    base_url = os.getenv("LLM_BASE_URL", "")
    if base_url:
        extra["api_base"] = base_url
        if "/" not in model:
            model = f"openai/{model}"
        key = os.getenv(_KEY_MAP.get(os.getenv("LLM_PROVIDER", ""), ""), "")
        if key:
            extra["api_key"] = key
    return model, extra
