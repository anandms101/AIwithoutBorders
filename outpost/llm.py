"""Shared Ollama client.

Every model call in Outpost goes through here so three things are guaranteed in
one place:

* ``keep_alive=-1`` on every request — AGENTS.md invariant 6. Models must stay
  resident or the always-on claim collapses.
* ``num_ctx`` pinned per role. Resident memory is dominated by context length,
  not parameter count: ``ollama ps`` showed ``phi4-mini:3.8b`` holding 20GB
  purely because its context defaulted to 131k.
* Local-only endpoint — AGENTS.md invariant 1. No remote inference, ever.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

from outpost.config import Settings, settings


class OllamaError(RuntimeError):
    """Ollama was unreachable or returned an unusable response."""


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from a model response.

    Local models wrap JSON in prose or fences no matter how firmly the prompt
    says otherwise, and ``medgemma`` cannot use tool calling at all. Callers must
    still apply a deterministic fallback when this returns ``None`` -- never let
    unparseable prose reach the database (ARCHITECTURE §5).
    """
    if not text:
        return None

    candidates: list[str] = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    # First balanced {...} span, so trailing prose does not break the parse.
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class OllamaClient:
    """Thin synchronous wrapper over the local Ollama HTTP API."""

    def __init__(self, config: Settings | None = None) -> None:
        self._settings = config or settings
        self._base_url = self._settings.ollama_host.rstrip("/")
        self._timeout = self._settings.request_timeout_seconds

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = httpx.post(url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            # Include the body: Ollama puts the actual reason there, and a bare
            # status code sends you hunting for nothing.
            body = exc.response.text[:500]
            raise OllamaError(
                f"Ollama request to {url} failed: {exc.response.status_code} {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request to {url} failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ollama returned non-JSON from {url}: {exc}") from exc

    def generate(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: list[Path] | None = None,
        num_ctx: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Run a single completion. Returns the raw response text."""
        options: dict[str, Any] = {"temperature": temperature}
        if num_ctx:
            options["num_ctx"] = num_ctx

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._settings.ollama_keep_alive,
            "options": options,
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = [
                base64.b64encode(Path(image).read_bytes()).decode("ascii")
                for image in images
            ]

        data = self._post("/api/generate", payload)
        return str(data.get("response", ""))

    def generate_json(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        images: list[Path] | None = None,
        num_ctx: int | None = None,
        retries: int = 1,
    ) -> dict[str, Any] | None:
        """Run a completion and parse JSON, retrying once on unparseable output.

        Returns ``None`` when every attempt fails so the caller can apply its
        deterministic fallback (ARCHITECTURE §5).
        """
        attempt_prompt = prompt
        for attempt in range(retries + 1):
            try:
                raw = self.generate(
                    model,
                    attempt_prompt,
                    system=system,
                    images=images,
                    num_ctx=num_ctx,
                )
            except OllamaError:
                if attempt >= retries:
                    raise
                continue

            parsed = extract_json(raw)
            if parsed is not None:
                return parsed

            attempt_prompt = (
                f"{prompt}\n\n"
                "Your previous reply was not valid JSON. Reply with ONLY a JSON "
                "object. No prose, no code fence, no explanation."
            )
        return None

    def embed(self, model: str, text: str) -> list[float]:
        """Return a single embedding vector."""
        data = self._post(
            "/api/embed",
            {
                "model": model,
                "input": text,
                "keep_alive": self._settings.ollama_keep_alive,
            },
        )
        embeddings = data.get("embeddings") or []
        if not embeddings:
            raise OllamaError(f"No embedding returned for model {model}")
        return [float(value) for value in embeddings[0]]

    def health(self) -> bool:
        """True when the local Ollama endpoint answers."""
        try:
            response = httpx.get(f"{self._base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True


client = OllamaClient()
