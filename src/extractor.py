"""LLM-first authorised-capital extraction with regex fallback; PAS-3 issued-capital helper."""

from __future__ import annotations

import logging
import re
from typing import Optional

from .llm_client import call_llm
from .models import DocumentType, ExtractedCapitalChange, ShareClass
from .utils import (
    extract_iso_date,
    extract_statutory_notice_date,
    parse_money_amount,
    parse_share_classes,
    read_text,
    safe_json_loads,
)

logger = logging.getLogger(__name__)


def _regex_extract_capital_change(text: str) -> ExtractedCapitalChange:
    old_amt: Optional[int] = None
    new_amt: Optional[int] = None
    t = text.lower()

    # Board/EGM/NB: handle patterns like "from existing Rs. 1,50,000 ... to Rs. 3,00,000"
    pair_re = re.search(
        r"from\s+(?:[\w\s-]+?\s+)?Rs\.?\s*(?:/-\s*)?([0-9][0-9,]*)\s*.*?\bto\s+Rs\.?\s*(?:/-\s*)?([0-9][0-9,]*)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if pair_re:
        old_amt = parse_money_amount(pair_re.group(1))
        new_amt = parse_money_amount(pair_re.group(2))

    if new_amt is None and ("form no. sh-7" not in t and "notice to registrar" not in t):
        # MOA may say "Rs. /- 3,00,000" (no explicit from->to pair).
        final_re = re.search(
            r"Authori[sz]ed\s+Share\s+Capital.*?\bRs\.?\s*(?:/-\s*)?([0-9][0-9,]*)\s*/?-?",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if final_re:
            new_amt = parse_money_amount(final_re.group(1))

    # SH-7 form uses tables with "Existing" and "Revised" values (not "from Rs.. to Rs..").
    if new_amt is None or old_amt is None:
        inc_word = re.search(r"(increased|decreased)\s+from", text, flags=re.IGNORECASE)
        if inc_word:
            after = text[inc_word.end() :]
            table_end = after.lower().find("</table>")
            table_text = after[:table_end] if table_end != -1 else after

            existing_m = re.search(r"Existing.*?([0-9][0-9,]*)", table_text, flags=re.IGNORECASE | re.DOTALL)
            revised_m = re.search(r"Revised.*?([0-9][0-9,]*)", table_text, flags=re.IGNORECASE | re.DOTALL)
            if old_amt is None and existing_m:
                old_amt = parse_money_amount(existing_m.group(1))
            if new_amt is None and revised_m:
                new_amt = parse_money_amount(revised_m.group(1))

        if new_amt is None:
            # SH-7 also contains an explicit authorised capital field.
            authorised_field_re = re.search(
                r"Authori[sz]ed\s+capital\s+of\s+the\s+company.*?\(in\s+Rs\.?\)\s*([0-9][0-9,]*)",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if authorised_field_re:
                new_amt = parse_money_amount(authorised_field_re.group(1))

    d = extract_iso_date(text)
    sc_raw = parse_share_classes(text)
    share_classes: list[ShareClass] = []
    for sc in sc_raw:
        share_classes.append(
            ShareClass(
                class_name=str(sc["class_name"]),
                num_shares=int(sc["num_shares"]),
                nominal_value=int(sc["nominal_value"]),
                amount=int(sc["amount"]),
            )
        )

    confidence = 0.4
    if new_amt is not None:
        confidence = 0.65 if old_amt is not None else 0.55
    if old_amt is not None and new_amt is not None:
        confidence = 0.8
    return ExtractedCapitalChange(
        old_authorised_capital=old_amt,
        new_authorised_capital=new_amt,
        date=d,
        share_classes=share_classes,
        confidence=confidence,
    )


def extract_capital_change(
    text: str,
    doc_type: DocumentType,
    extraction_prompt_path: str = "prompts/extraction_prompt.txt",
) -> ExtractedCapitalChange:
    """
    Extract confirmed authorised-capital change values.

    Strategy:
    1. Try LLM extraction via `call_llm()`, expecting strict JSON.
    2. If the LLM fails (missing API key, rate limits, invalid JSON, etc), fall back
       to deterministic regex/table extraction (`_regex_extract_capital_change()`).
    """
    prompt_template = read_text(extraction_prompt_path)
    full_prompt = (
        f"{prompt_template}\n\nDocument type: {doc_type}\n\n"
        f"Document text:\n{text}\n"
    )

    try:
        logger.debug("LLM extraction attempt for %s", doc_type)
        raw = call_llm(full_prompt)
        parsed = safe_json_loads(raw)
        # Pydantic validation happens here.
        out = ExtractedCapitalChange(**parsed)
        # If critical fields missing, fall back to regex extraction.
        if out.new_authorised_capital is None and out.old_authorised_capital is None:
            return _regex_extract_capital_change(text)
        if (sd := extract_statutory_notice_date(text)) is not None:
            out = out.model_copy(update={"date": sd})
        elif out.date is None:
            fallback = extract_iso_date(text)
            if fallback is not None:
                out = out.model_copy(update={"date": fallback})
        return out
    except Exception as e:
        logger.warning("LLM extraction failed (or parse invalid), using regex fallback: %s", e)
        return _regex_extract_capital_change(text)


def extract_pas3_issued_capital(text: str) -> Optional[int]:
    """
    Rule-based PAS-3 issued-capital extraction (used for validation only).
    """
    patterns = [
        r"TOTAL\s+PAID-UP\s*\(ISSUED\)\s*CAPITAL\s*:\s*Rs\.?\s*([0-9][0-9,]*)",
        r"issued\s*capital\s*:\s*Rs\.?\s*([0-9][0-9,]*)",
        r"Total\s+nominal\s+value\s+of\s+shares\s+allotted\s*\(issued\s+capital\)\s*:\s*Rs\.?\s*([0-9][0-9,]*)",
        r"Total\s+nominal\s+value\s+of\s+shares\s+allotted\s*\(issued\s+capital\)\s*Rs\.?\s*([0-9][0-9,]*)",
        # HTML-table SH-7/PAS forms (covers "Total nominal amount (in Rs.) 9600")
        r"Total\s+nominal\s+amount.*?\(in\s+Rs\.?\)\s*([0-9][0-9,]*)",
        r"Total\s+nominal\s+amount.*?<td>\(in\s+Rs\.?\)</td>\s*<td>\s*([0-9][0-9,]*)",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return parse_money_amount(m.group(1))
    return None

