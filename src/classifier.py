"""
Document classification (LLM) and optional routing of raw files into the structured layout.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .llm_client import call_llm
from .models import DocumentClassification
from .utils import read_text, safe_json_loads

if TYPE_CHECKING:
    from .documents.routing import RawDataRoutingPipeline
    from .io.formats import FormatRegistry

logger = logging.getLogger(__name__)

_UNCLASSIFIED_CACHE: set[str] | None = None

_DOC_TYPE_RE = re.compile(
    r"\b(SH7|BOARD_RESOLUTION|EGM_RESOLUTION|MOA|EGM_NOTICE|PAS3|UNKNOWN)\b",
    flags=re.IGNORECASE,
)
_AUTH_RE = re.compile(r"\b(high|medium|low|unknown)\b", flags=re.IGNORECASE)
_EVENT_RE = re.compile(r"\b(capital_change|share_allotment|proposal|unknown)\b", flags=re.IGNORECASE)


# --- Unclassified / ignore list (env) ---


def _load_unclassified_paths() -> set[str]:
    """
    Paths or basenames to skip, from `UNCLASSIFIED_DOCS_FILE` or comma-separated `UNCLASSIFIED_DOCS`.
    """
    global _UNCLASSIFIED_CACHE
    if _UNCLASSIFIED_CACHE is not None:
        return _UNCLASSIFIED_CACHE

    items: set[str] = set()
    file_path = (
        Path(os.getenv("UNCLASSIFIED_DOCS_FILE", "")).expanduser().resolve()
        if os.getenv("UNCLASSIFIED_DOCS_FILE")
        else None
    )
    if file_path and file_path.exists():
        try:
            for line in file_path.read_text(encoding="utf-8").splitlines():
                v = line.strip()
                if v:
                    items.add(v)
        except Exception:
            logger.exception("Failed reading UNCLASSIFIED_DOCS_FILE=%s", file_path)

    env_list = os.getenv("UNCLASSIFIED_DOCS", "").strip()
    if env_list:
        for part in env_list.split(","):
            v = part.strip()
            if v:
                items.add(v)

    _UNCLASSIFIED_CACHE = items
    return items


def _is_ignored_path(source_path: str) -> bool:
    ignored = _load_unclassified_paths()
    if not ignored:
        return False
    base = Path(source_path).name
    return any(source_path == item or base == item or item in source_path for item in ignored)


# --- LLM response coercion ---


def _coerce_classification_payload(payload: dict) -> Optional[dict]:
    """Convert near-miss strings into enum-compatible dict, or None."""

    def _pick(re_obj: re.Pattern, val: object) -> Optional[str]:
        if not isinstance(val, str):
            return None
        m = re_obj.search(val)
        return m.group(1) if m else None

    doc_type_raw = payload.get("document_type")
    auth_raw = payload.get("authority")
    event_raw = payload.get("event")
    conf_raw = payload.get("confidence")

    doc_type = _pick(_DOC_TYPE_RE, doc_type_raw)
    if doc_type:
        doc_type = doc_type.upper()
    authority = _pick(_AUTH_RE, auth_raw)
    event = _pick(_EVENT_RE, event_raw)

    if doc_type is None or authority is None or event is None:
        return None

    try:
        confidence = float(conf_raw or 0.1)
    except Exception:
        confidence = 0.1
    confidence = max(0.0, min(1.0, confidence))

    return {
        "document_type": doc_type,
        "authority": authority.lower(),
        "event": event.lower(),
        "confidence": confidence,
    }


def _unknown_classification(confidence: float = 0.05) -> DocumentClassification:
    return DocumentClassification(
        document_type="UNKNOWN",
        authority="unknown",
        event="unknown",
        confidence=confidence,
    )


# --- Public API ---


def classify_document(
    text: str,
    classification_prompt_path: str = "prompts/classification_prompt.txt",
    *,
    source_path: str | None = None,
) -> DocumentClassification:
    """
    Classify with the LLM; respect ignore list; on failure return UNKNOWN with low confidence.
    """
    if source_path and _is_ignored_path(source_path):
        return _unknown_classification(confidence=0.0)

    logger.debug("LLM classification attempt for %s", source_path)
    prompt_template = read_text(classification_prompt_path)
    full_prompt = f"{prompt_template}\n\nDocument text:\n{text}\n"

    try:
        raw = call_llm(full_prompt)
        parsed = safe_json_loads(raw)
        try:
            return DocumentClassification(**parsed)
        except Exception:
            if isinstance(parsed, dict):
                coerced = _coerce_classification_payload(parsed)
                if coerced is not None:
                    return DocumentClassification(**coerced)
            raise
    except Exception as e:
        logger.exception("Failed to parse classification JSON: %s", e)
        return _unknown_classification(confidence=0.05)


def route_raw_data_to_structured(
    *,
    raw_root: str = "data/raw_data",
    structured_root: str = "data",
    format_registry: FormatRegistry | None = None,
    routing_pipeline: RawDataRoutingPipeline | None = None,
) -> None:
    """
    Read unstructured files under `raw_root`, classify, write structured tree for `load_dataset`.
    """
    from .documents.routing import route_raw_data_to_structured as _route_impl

    _route_impl(
        raw_root=raw_root,
        structured_root=structured_root,
        format_registry=format_registry,
        routing_pipeline=routing_pipeline,
        classify_document=classify_document,
    )
