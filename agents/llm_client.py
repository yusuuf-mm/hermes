"""
llm_client.py
-------------
Single shared client layer for all HERMES agents.

Two providers:
  - Groq              (Agents 1-3, 5)  — GROQ_API_KEY, low-latency Llama 3
  - GitLawb Opengateway (Agent 4)      — GITLAWB_API_KEY, Xiaomi Mimo v2.5 Pro

Every agent imports get_client() and model aliases from here.
"""

from __future__ import annotations

import os
import time
from openai import OpenAI, RateLimitError, APIStatusError


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def _groq_client() -> OpenAI:
    """Groq-hosted Llama 3 models — fast inference."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set in .env")
    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )


def _gitlawb_client() -> OpenAI:
    """GitLawb Opengateway — Xiaomi Mimo v2.5 Pro (long-horizon MoE)."""
    api_key = os.environ.get("GITLAWB_API_KEY")
    if not api_key:
        raise EnvironmentError("GITLAWB_API_KEY is not set in .env")
    return OpenAI(
        api_key=api_key,
        base_url="https://opengateway.gitlawb.com/v1",
        default_headers={"Accept-Encoding": "identity"},
    )


# Singleton clients (lazy-init)
_groq: OpenAI | None = None
_gitlawb: OpenAI | None = None


def _get_groq() -> OpenAI:
    global _groq
    if _groq is None:
        _groq = _groq_client()
    return _groq


def _get_gitlawb() -> OpenAI:
    global _gitlawb
    if _gitlawb is None:
        _gitlawb = _gitlawb_client()
    return _gitlawb


# ---------------------------------------------------------------------------
# Model aliases
# ---------------------------------------------------------------------------

# Agents 1 & 2: Monitoring + Classification — low-latency fast inference
MONITORING_MODEL    = "llama-3.1-8b-instant"
CLASSIFICATION_MODEL = "llama-3.1-8b-instant"

# Agents 3 & 5: SLA Risk + Dispatch — deep reasoning, larger context
SLA_RISK_MODEL = "llama-3.3-70b-versatile"
DISPATCH_MODEL = "llama-3.3-70b-versatile"

# Agent 4: Rerouting — long-horizon MoE intelligence via GitLawb
REROUTING_MODEL = "xiaomi/mimo-v2.5-pro"


# ---------------------------------------------------------------------------
# Model → provider routing
# ---------------------------------------------------------------------------

_GITLAWB_MODELS = {REROUTING_MODEL}


def _client_for(model: str) -> OpenAI:
    """Pick the right provider client for a given model tag."""
    if model in _GITLAWB_MODELS:
        return _get_gitlawb()
    return _get_groq()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def complete(
    system_prompt: str,
    user_message: str,
    model: str = MONITORING_MODEL,
    max_tokens: int = 1000,
) -> str:
    """
    Single convenience wrapper used by every agent.
    Returns the text content of the first choice.
    """
    client = _client_for(model)

    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            if content is None:
                # MoE reasoning model may exhaust tokens before emitting content
                raise RuntimeError(
                    f"Model {model} returned empty content "
                    f"(finish_reason={response.choices[0].finish_reason}). "
                    "Increase max_tokens."
                )
            return content.strip()
        except (RateLimitError, APIStatusError) as e:
            is_429 = isinstance(e, RateLimitError) or (
                hasattr(e, "status_code") and e.status_code == 429
            )
            if is_429 and attempt < 3:
                wait = 2 ** attempt * 5
                print(f"  Rate limited ({model}), retry {attempt+1}/4 in {wait}s...")
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"All retries exhausted for {model}")
