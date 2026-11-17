"""OpenRouter (OpenAI-compatible; models ending in ':free' cost nothing,
and 'openrouter/free' routes to an available free model)."""
from .openai_compat import OpenAICompatProvider


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"

    def extra_headers(self) -> dict:
        return {"X-Title": "ASKAI 8086 Assistant"}

    def list_models(self) -> list[str]:
        return [m for m in super().list_models() if m.endswith(":free") or m == "openrouter/free"]
