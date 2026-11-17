"""Shared adapter for OpenAI-compatible chat-completions APIs
(OpenAI, Groq, OpenRouter)."""
from __future__ import annotations

from .base import ChatResult, Provider, ProviderError, classify_status, http_json, retry_after_of


class OpenAICompatProvider(Provider):
    name = "openai-compatible"
    base_url = ""
    max_tokens_field = "max_tokens"
    max_output_cap = 8192          # many models reject more; longer answers are continued

    def extra_headers(self) -> dict:
        return {}

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}"}
        h.update(self.extra_headers())
        return h

    def chat(self, model, system, messages, *, max_tokens, temperature=0.2) -> ChatResult:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}] + [
                {"role": m["role"], "content": m["content"]} for m in messages],
            self.max_tokens_field: min(max_tokens, self.max_output_cap),
        }
        if temperature is not None:
            body["temperature"] = temperature
        status, data = http_json("POST", f"{self.base_url}/chat/completions",
                                 self._headers(), body, self.timeout)
        if status != 200:
            err = data.get("error") if isinstance(data, dict) else None
            msg = (err.get("message") if isinstance(err, dict) else str(err or data))[:400]
            code = str(err.get("code", "")) if isinstance(err, dict) else ""
            kind = classify_status(status, msg + " " + code)
            raise ProviderError(kind, f"{self.name} {model}: {msg}", status=status,
                                retry_after=retry_after_of(data))
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("unavailable", f"{self.name} {model}: empty response")
        ch = choices[0]
        text = ((ch.get("message") or {}).get("content")) or ""
        if not text.strip():
            raise ProviderError("unavailable", f"{self.name} {model}: empty answer")
        usage = data.get("usage") or {}
        return ChatResult(
            text=text, provider=self.name, model=data.get("model", model),
            in_tokens=int(usage.get("prompt_tokens", 0) or 0),
            out_tokens=int(usage.get("completion_tokens", 0) or 0),
            truncated=ch.get("finish_reason") == "length",
        )

    def list_models(self) -> list[str]:
        status, data = http_json("GET", f"{self.base_url}/models", self._headers(), None, 30)
        if status != 200:
            msg = str(data.get("error", data))[:200]
            raise ProviderError(classify_status(status, msg), f"{self.name}: {msg}", status=status)
        return sorted(m.get("id", "") for m in data.get("data", []))
