"""OpenAI (optional provider; requires a paid account with credits)."""
from .openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    name = "openai"
    base_url = "https://api.openai.com/v1"
    max_tokens_field = "max_completion_tokens"
