"""Thin wrapper around the `monid` CLI.

Monid is the only external data boundary in this project, so the rest of the
code talks to it through this module and never shells out directly.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class MonidError(RuntimeError):
    """Raised when a Monid run does not complete successfully."""


def run_endpoint(
    provider: str,
    endpoint: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    path: dict[str, Any] | None = None,
    wait_seconds: int = 120,
) -> dict[str, Any]:
    """Execute a Monid endpoint and return its `output` payload."""
    cmd = ["monid", "run", "-p", provider, "-e", endpoint, "-j"]
    if body is not None:
        cmd += ["-i", json.dumps(body)]
    if query is not None:
        cmd += ["--query", json.dumps(query)]
    if path is not None:
        cmd += ["--path", json.dumps(path)]
    cmd += ["-w", str(wait_seconds)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=wait_seconds + 90
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment issue
        raise MonidError("`monid` CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MonidError(f"monid timed out after {wait_seconds}s") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise MonidError(
            f"monid exited {proc.returncode}: {detail[-1] if detail else 'no output'}"
        )

    payload = _parse_json(proc.stdout)

    # A failed *provider* call still reports status "COMPLETED": the Monid run
    # itself finished, it is the upstream request that failed and left `output`
    # null. Surface the provider's own error rather than an opaque message.
    error = payload.get("error")
    if error:
        raise MonidError(f"monid error: {_describe_error(error)}")

    status = payload.get("status")
    if status != "COMPLETED":
        cost = payload.get("controls") or payload.get("error")
        raise MonidError(f"monid run status {status!r} ({cost})")

    output = payload.get("output")
    if not isinstance(output, dict):
        raise MonidError(f"monid run produced no output: {_provider_failure(payload)}")
    return output


def _provider_failure(payload: dict[str, Any]) -> str:
    """Explain why a completed run has no output (almost always a provider error)."""
    response = payload.get("providerResponse") or {}
    status = response.get("httpStatus")
    message = _describe_error(response.get("error")) if response.get("error") else ""
    parts = [p for p in (f"HTTP {status}" if status is not None else "", message) if p]
    return f"provider returned {' - '.join(parts)}" if parts else "provider returned no output"


def _describe_error(error: Any) -> str:
    """Pull a human-readable message out of Monid's various error shapes."""
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return str(error)
    detail = error.get("detail")
    if isinstance(detail, dict) and detail.get("message"):
        return str(detail["message"])
    if isinstance(detail, str) and detail:
        return detail
    for key in ("message", "code"):
        if error.get(key):
            return str(error[key])
    return json.dumps(error)[:300]


def _parse_json(stdout: str) -> dict[str, Any]:
    """Parse the JSON object out of stdout, tolerating any leading noise."""
    start = stdout.find("{")
    if start == -1:
        raise MonidError(f"no JSON in monid output: {stdout[:200]!r}")
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        raise MonidError(f"could not decode monid JSON: {exc}") from exc
