"""OpenClaw harness — the agent runtime (AGENTS.md tech stack).

Outpost drives OpenClaw locally via its CLI:

    openclaw agent --local --session-key <key> --message <prompt>

``--local`` runs the turn embedded rather than through a gateway daemon, which
keeps the heartbeat self-contained. OpenClaw is configured against the local
Ollama endpoint, so invariant 1 holds: no remote inference in the runtime path.

**Why the agent does not execute tools itself.** Tool dispatch stays in Python
(``alerting.py`` calls ``tools.py`` directly) and OpenClaw is handed the already
-retrieved structured counts to reason over and narrate. That is deliberate:

* Invariant 5 — alerts fire on structured fields only. If the model chose its
  own tool arguments it could ask for a window or catchment that manufactures a
  cluster. The threshold decision must be arithmetic, not generation.
* A 12B local model is not reliable enough at multi-step tool calling to put on
  stage, and the 30s heartbeat has no budget for retries.

So OpenClaw does what a local model is genuinely good at: turning verified
numbers into a clinician-readable rationale. Every tool call still lands in the
trace, because Python made it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

from outpost import trace
from outpost.config import Settings, settings
from outpost.llm import extract_json

# OpenClaw prefixes runtime diagnostics onto stdout; strip them to isolate the
# reply. Observed prefixes on 2026.7.1-2.
_NOISE_PREFIXES = (
    "[diagnostic]",
    "[provider-transport-fetch]",
    "[model-fallback",
    "[agent/",
    "[agents/",
    "[gateway",
    "[plugins",
    "[secrets",
    "[memory",
    "[compaction",
    "[context-overflow",
)

# OpenClaw reports some failures as ordinary stdout prose rather than a non-zero
# exit, so they would otherwise be stored as a clinician-facing rationale.
_FAILURE_MARKERS = (
    "context overflow:",
    "prompt too large",
    "no api key found",
    "failovererror",
    "providerautherror",
)

# OpenClaw colourises diagnostics even when stdout is not a TTY, so the prefix
# match has to happen after the escape codes are removed. --no-color is passed
# as well; this is the belt to that braces.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class OpenClawError(RuntimeError):
    """OpenClaw was unavailable or returned nothing usable."""


@dataclass(frozen=True)
class AgentReply:
    """One completed agent turn."""

    text: str
    session_key: str
    duration_ms: int
    fallback: bool = False


def is_available() -> bool:
    """True when the openclaw CLI is on PATH."""
    return shutil.which("openclaw") is not None


def version() -> str | None:
    if not is_available():
        return None
    try:
        completed = subprocess.run(
            ["openclaw", "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return completed.stdout.strip() or None


def clean_output(raw: str) -> str:
    """Drop OpenClaw's diagnostic lines, keeping the model's reply."""
    plain = _ANSI_RE.sub("", raw or "")
    kept = [
        line
        for line in plain.splitlines()
        if line.strip() and not line.lstrip().startswith(_NOISE_PREFIXES)
    ]
    return "\n".join(kept).strip()


def run_turn(
    message: str,
    *,
    session_key: str | None = None,
    timeout: int | None = None,
    config: Settings | None = None,
) -> AgentReply:
    """Run one OpenClaw agent turn locally."""
    config = config or settings
    session_key = session_key or f"outpost-{uuid.uuid4().hex[:8]}"
    timeout = timeout or config.request_timeout_seconds

    if not is_available():
        raise OpenClawError("openclaw CLI not found on PATH")

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [
                "openclaw",
                "--no-color",
                "agent",
                "--local",
                "--session-key",
                session_key,
                "--message",
                message,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenClawError(f"openclaw turn timed out after {timeout}s") from exc
    except OSError as exc:
        raise OpenClawError(f"failed to launch openclaw: {exc}") from exc

    duration_ms = int((time.perf_counter() - started) * 1000)
    text = clean_output(completed.stdout)

    if not text:
        stderr = clean_output(completed.stderr)[:300]
        raise OpenClawError(
            f"openclaw returned no usable output (exit {completed.returncode}): {stderr}"
        )

    # OpenClaw prints some failures as plain stdout and still exits 0. Without
    # this check the words "Context overflow: prompt too large" would be stored
    # as an alert rationale and shown to a clinician.
    lowered = text.lower()
    if any(marker in lowered for marker in _FAILURE_MARKERS):
        raise OpenClawError(f"openclaw reported a failure: {text[:200]}")

    return AgentReply(text=text, session_key=session_key, duration_ms=duration_ms)


def narrate(
    system_context: str,
    facts: dict,
    *,
    session_key: str | None = None,
    connection=None,
    config: Settings | None = None,
) -> AgentReply | None:
    """Ask OpenClaw to turn verified facts into clinician-readable prose.

    Returns ``None`` when OpenClaw is unavailable so callers can fall back to a
    deterministic template — the heartbeat must never stall on the agent.
    """
    config = config or settings
    prompt = (
        f"{system_context}\n\n"
        f"Verified surveillance figures (already computed, do not recompute):\n"
        f"{json.dumps(facts, indent=2)}\n"
    )

    trace_id = trace.record(
        "agent", "openclaw_narrate", {"facts": facts},
        connection=connection, config=config,
    )
    started = time.perf_counter()
    try:
        reply = run_turn(prompt, session_key=session_key, config=config)
    except OpenClawError as exc:
        trace.update(
            trace_id,
            result_summary=f"ERROR {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=connection,
            config=config,
        )
        return None

    trace.update(
        trace_id,
        result_summary=f"{len(reply.text)} chars in {reply.duration_ms}ms",
        duration_ms=reply.duration_ms,
        connection=connection,
        config=config,
    )
    return reply


def narrate_json(
    system_context: str,
    facts: dict,
    *,
    session_key: str | None = None,
    connection=None,
    config: Settings | None = None,
) -> dict | None:
    """``narrate`` with a JSON-parsed reply, or ``None`` if unusable."""
    reply = narrate(
        system_context, facts,
        session_key=session_key, connection=connection, config=config,
    )
    if reply is None:
        return None
    return extract_json(reply.text)
