"""
Worker subprocess for LLM API calls.
Run via: python -m agents._complete_worker < json_input
"""
from __future__ import annotations

import json
import os
import sys
import time

from openai import APIStatusError, OpenAI, RateLimitError


def main() -> None:
    data = json.loads(sys.stdin.read())
    api_key: str = data["api_key"]
    base_url: str = data["base_url"]
    model: str = data["model"]
    max_tokens: int = data["max_tokens"]
    temperature: float = data["temperature"]
    system_prompt: str = data["system_prompt"]
    user_message: str = data["user_message"]

    client = OpenAI(api_key=api_key, base_url=base_url)
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
            )
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError(
                    f"Model {model} returned empty content "
                    f"(finish_reason={response.choices[0].finish_reason})."
                )
            content = content.strip()
            # Strip ```json ... ``` fences that gemma-3n adds around JSON.
            if content.startswith("```"):
                first_nl = content.find("\n")
                if first_nl != -1:
                    content = content[first_nl + 1:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            print(json.dumps({"ok": True, "content": content}))
            return
        except (RateLimitError, APIStatusError) as e:
            is_429 = isinstance(e, RateLimitError) or (
                hasattr(e, "status_code") and e.status_code == 429
            )
            if is_429 and attempt < 3:
                wait = 2 ** attempt * 5
                print(json.dumps({"ok": False, "retry": True,
                                  "message": f"Rate limited ({model}), retry {attempt+1}/4 in {wait}s..."}),
                      file=sys.stderr)
                time.sleep(wait)
            else:
                print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
                sys.exit(1)

    print(json.dumps({"ok": False, "error": f"All retries exhausted for {model}"}),
          file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
