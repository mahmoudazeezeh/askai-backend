"""Google Gemini (Generative Language API, REST)."""
from __future__ import annotations

from .base import ChatResult, Provider, ProviderError, classify_status, http_json, retry_after_of

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(Provider):
    name = "gemini"

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key}

    def chat(self, model, system, messages, *, max_tokens, temperature=0.2) -> ChatResult:
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        status, data = http_json("POST", f"{BASE}/models/{model}:generateContent",
                                 self._headers(), body, self.timeout)
        if status != 200:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            msg = err.get("message") or str(data)[:300]
            kind = classify_status(status, msg + " " + str(err.get("status", "")))
            if status == 400 and "API_KEY_INVALID" in str(data):
                kind = "auth"
            raise ProviderError(kind, f"Gemini {model}: {msg}", status=status,
                                retry_after=retry_after_of(data))
        cands = data.get("candidates") or []
        if not cands:
            block = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            raise ProviderError("bad_request", f"Gemini returned no answer ({block})")
        cand = cands[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise ProviderError("unavailable", f"Gemini {model} returned an empty answer "
                                               f"(finishReason={cand.get('finishReason')})")
        um = data.get("usageMetadata") or {}
        return ChatResult(
            text=text, provider=self.name, model=model,
            in_tokens=int(um.get("promptTokenCount", 0)),
            out_tokens=int(um.get("candidatesTokenCount", 0)) + int(um.get("thoughtsTokenCount", 0)),
            truncated=cand.get("finishReason") == "MAX_TOKENS",
        )

    def list_models(self) -> list[str]:
        status, data = http_json("GET", f"{BASE}/models?pageSize=200", self._headers(), None, 30)
        if status != 200:
            msg = (data.get("error") or {}).get("message", str(data)[:200])
            raise ProviderError(classify_status(status, msg), f"Gemini: {msg}", status=status)
        return sorted(
            m["name"].removeprefix("models/") for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        )
