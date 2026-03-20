"""OpenAI chat client with retries (rate limits, transient errors)."""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from openai import APIConnectionError, APITimeoutError, RateLimitError

load_dotenv()

logger = logging.getLogger(__name__)


def call_llm(prompt: str) -> str:
    """
    LLM wrapper used by both classification and extraction.

    Notes:
    - This function assumes `OPENAI_API_KEY` is present in the current environment.
    - Retry logic primarily targets transient failures and rate limiting.
    """
    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(base_url=api_base, api_key=api_key)

    last_err: Optional[Exception] = None
    max_attempts = int(os.getenv("LLM_MAX_ATTEMPTS", "6"))

    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content or ""
        except RateLimitError as e:
            last_err = e
            # If the SDK surfaces it, respect Retry-After.
            wait_s = 2.0 * (2 ** (attempt - 1))
            retry_after = getattr(getattr(e, "response", None), "headers", {}).get("retry-after")
            if retry_after:
                try:
                    wait_s = float(retry_after)
                except ValueError:
                    pass
            wait_s = min(60.0, wait_s) + random.uniform(0, 0.25)
            logger.warning("LLM rate limited (attempt %s): %s. Retrying in %.1fs", attempt, e, wait_s)
            time.sleep(wait_s)
        except (APITimeoutError, APIConnectionError) as e:
            last_err = e
            wait_s = min(60.0, 1.0 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
            logger.warning("LLM transient failure (attempt %s): %s. Retrying in %.1fs", attempt, e, wait_s)
            time.sleep(wait_s)
        except Exception as e:
            last_err = e
            logger.warning("LLM call failed (attempt %s): %s. Retrying may be unsafe.", attempt, e)
            # Retry once more for other errors.
            wait_s = min(30.0, 1.0 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
            time.sleep(wait_s)

    raise RuntimeError(f"LLM call failed after retries: {last_err}")
