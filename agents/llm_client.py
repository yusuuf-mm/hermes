"""
llm_client.py
-------------
Single shared client layer for all HERMES agents.

Provider: NVIDIA NIM
  - https://integrate.api.nvidia.com/v1
  - NVIDIA_API_KEY (env var)
  - temperature=0.2 (hard-coded inside complete() — not a parameter, not overridable)

`MODEL_REGISTRY` is the single source of truth for model selection.
Every agent imports `MODEL_REGISTRY` and passes `model=MODEL_REGISTRY["<role>"]`
to `complete()` explicitly — no hidden indirection helpers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
TEMPERATURE = 0.2  # used by complete() — not exported for override


# ---------------------------------------------------------------------------
# Model registry — single source of truth
# ---------------------------------------------------------------------------
#
# Keys are agent roles, NOT graph node names. The classification node is
# registered under "ingestion" because its job is to ingest raw events
# into typed classifications (a.k.a. the Ingestion Agent). The graph
# node-name "classification" is preserved in graph.py and telemetry.py
# for DB continuity; the thin mapping lives in agents/telemetry.py.
#
# Forward-compat: "optimizer" is reserved for a future SQL/function-calling
# agent. No current agent references it.

# ---------------------------------------------------------------------------
# Model profiles
# ---------------------------------------------------------------------------
# Set HERMES_MODEL_PROFILE in the environment to switch profiles:
#   - "demo"  (default): all-gemma — fastest, ~100-120s per full tick.
#                         Best for GIF recording and live demos.
#   - "prod":            production tier — maverick for deep reasoning,
#                         qwen-coder for rerouting. ~240s per full tick.
#   - "balanced":        qwen-coder for everything — ~70s per tick.
# Override individual agents with HERMES_MODEL_<AGENT>=<model>.
#
# Tested latencies with compressed prompts (8-26 lines) and max_tokens
# 200-400:
#   google/gemma-3n-e2b-it              ~12s/call
#   qwen/qwen3-coder-480b-a35b-instruct ~14s/call
#   meta/llama-4-maverick-17b-128e      ~48s/call

_MODEL_PROFILES: dict[str, dict[str, str]] = {
    "demo": {
        "monitoring": "google/gemma-3n-e2b-it",
        "ingestion":  "google/gemma-3n-e2b-it",
        "sla_risk":   "google/gemma-3n-e2b-it",
        "rerouting":  "google/gemma-3n-e2b-it",
        "dispatch":   "google/gemma-3n-e2b-it",
        "optimizer":  "mistralai/mistral-nemotron",
    },
    "prod": {
        "monitoring": "meta/llama-4-maverick-17b-128e-instruct",
        "ingestion":  "google/gemma-3n-e2b-it",
        "sla_risk":   "meta/llama-4-maverick-17b-128e-instruct",
        "rerouting":  "qwen/qwen3-coder-480b-a35b-instruct",
        "dispatch":   "meta/llama-4-maverick-17b-128e-instruct",
        "optimizer":  "mistralai/mistral-nemotron",
    },
    "balanced": {
        "monitoring": "qwen/qwen3-coder-480b-a35b-instruct",
        "ingestion":  "qwen/qwen3-coder-480b-a35b-instruct",
        "sla_risk":   "qwen/qwen3-coder-480b-a35b-instruct",
        "rerouting":  "qwen/qwen3-coder-480b-a35b-instruct",
        "dispatch":   "qwen/qwen3-coder-480b-a35b-instruct",
        "optimizer":  "mistralai/mistral-nemotron",
    },
}


def _resolve_model_registry() -> dict[str, str]:
    """Pick profile from HERMES_MODEL_PROFILE, then apply per-agent
    HERMES_MODEL_<AGENT> overrides from environment."""
    profile_name = os.environ.get("HERMES_MODEL_PROFILE", "demo").lower()
    profile = _MODEL_PROFILES.get(profile_name, _MODEL_PROFILES["demo"])
    registry = dict(profile)
    for key in list(registry.keys()):
        env_key = f"HERMES_MODEL_{key.upper()}"
        if env_key in os.environ:
            registry[key] = os.environ[env_key]
    return registry


MODEL_REGISTRY: dict[str, str] = _resolve_model_registry()


# ---------------------------------------------------------------------------
# Subprocess execution
# ---------------------------------------------------------------------------
# LangGraph's internal thread pool (BackgroundExecutor) causes a fatal
# "PyEval_SaveThread: GIL released" crash on Windows + Python 3.11 when
# httpx/OpenSSL performs SSL_read() from a pool thread with NULL thread
# state.  This is a CPython bug (3.11-specific) triggered by
# contextvars.copy_context().run() inside LangGraph's thread dispatch.
#
# Workaround: run each LLM API call in a child process via subprocess.
# The worker script is agents/_complete_worker.py (invoked as
# `python -m agents._complete_worker`).  Each child gets a clean
# interpreter, fresh SSL context, and proper thread state.
# Overhead on Windows is ~0.3s per call for process creation —
# acceptable for a multi-agent pipeline where each LLM call takes 3-30s.


def _complete_via_subprocess(
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
    base_url: str,
) -> str:
    """Dispatch the LLM call to a child process to avoid LangGraph's
    thread-pool SSL crash on Windows + Python 3.11."""
    payload = json.dumps({
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system_prompt": system_prompt,
        "user_message": user_message,
    })
    proc = subprocess.run(
        [sys.executable, "-m", "agents._complete_worker"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=600,
    )
    # stdout = JSON result; stderr = progress / debug
    if proc.stderr:
        for line in proc.stderr.strip().split("\n"):
            try:
                msg = json.loads(line)
                if not msg.get("ok") and msg.get("retry"):
                    print(f"  {msg['message']}")
            except json.JSONDecodeError:
                pass
    if proc.returncode != 0:
        raise RuntimeError(f"Worker failed (exit {proc.returncode}): {proc.stderr}")
    result = json.loads(proc.stdout)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Unknown worker error"))
    return result["content"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def complete(
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int = 1000,
) -> str:
    """
    Single convenience wrapper used by every agent.
    Returns the text content of the first choice.

    `model` must come from MODEL_REGISTRY — callers pass
    `model=MODEL_REGISTRY["<role>"]` explicitly.

    Temperature is hard-coded to 0.2 — not a parameter, not overridable.
    """
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise EnvironmentError("NVIDIA_API_KEY is not set in .env")

    return _complete_via_subprocess(
        system_prompt,
        user_message,
        model,
        max_tokens,
        TEMPERATURE,
        api_key,
        NVIDIA_BASE_URL,
    )
