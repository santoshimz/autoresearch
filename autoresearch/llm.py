from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib import error, parse, request


class TextGenerator(Protocol):
    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate structured JSON from a text prompt."""


@dataclass(frozen=True)
class GeminiTextGenerator:
    model: str
    api_key_env: str
    temperature: float = 0.2
    max_output_tokens: int = 4096
    api_base_url: str = "https://generativelanguage.googleapis.com/v1beta/models"

    def _load_api_key(self) -> str:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Missing API key for LLM candidate generation. Set the {self.api_key_env} environment variable."
            )
        return api_key

    def generate_json(self, prompt: str) -> dict[str, Any]:
        api_key = self._load_api_key()
        url = (
            f"{self.api_base_url}/{parse.quote(self.model, safe='')}:generateContent"
            f"?key={parse.quote(api_key, safe='')}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini request failed with HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Gemini request failed: {exc.reason}") from exc

        try:
            response_payload = json.loads(raw)
            text = response_payload["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Gemini response did not contain valid JSON candidate output.") from exc
