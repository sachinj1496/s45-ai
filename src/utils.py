"""IO helpers, parsing (money, dates, share classes, JSON), and export helpers."""

from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .models import CapitalTimelineOutput


def setup_logging(level: int = logging.INFO) -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def read_text(path: str) -> str:
    """Resolve path through `FormatRegistry` (plain text today; extend with PDF etc.)."""
    from .io.formats import get_default_format_registry

    return get_default_format_registry().read(path)


# --- Parsing ---

_FILING_REFERENCE_DATE_RE = re.compile(
    r"(?i)(?:filing\s*/\s*reference|reference\s*/\s*filing)\s+date\s*:\s*(20\d{2}-\d{2}-\d{2})\b"
)
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
# e.g. "15<sup>th</sup> DAY OF September 2024" in certified board copies
_SUP_ORDINAL_DAY_RE = re.compile(
    r"(?i)(\d{1,2})\s*<sup>\s*(?:st|nd|rd|th)\s*</sup>\s*DAY OF\s+(\w+)\s+(20\d{2})\b"
)
_PLAIN_ORDINAL_DAY_RE = re.compile(
    r"(?i)\b(\d{1,2})(?:st|nd|rd|th)\s+DAY OF\s+(\w+)\s+(20\d{2})\b"
)
_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _date_from_yyyy_mm_dd(s: str) -> Optional[date]:
    try:
        y, mo, d = (int(x) for x in s.split("-"))
        return date(y, mo, d)
    except ValueError:
        return None


def extract_filing_reference_iso_date(text: str) -> Optional[date]:
    """ISO date on a Filing/Reference (or Reference/Filing) line, if present."""
    m = _FILING_REFERENCE_DATE_RE.search(text)
    if not m:
        return None
    return _date_from_yyyy_mm_dd(m.group(1))


_MEETING_MEMBERS_HELD_RE = re.compile(
    r"(?i)Meeting of members held on:\s*(\d{1,2})/(\d{1,2})/(20\d{2})"
)


def extract_statutory_notice_date(text: str) -> Optional[date]:
    """SH-7 header dates: filing/reference ISO, else members' meeting DD/MM/YYYY."""
    fd = extract_filing_reference_iso_date(text)
    if fd is not None:
        return fd
    m = _MEETING_MEMBERS_HELD_RE.search(text)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _month_from_english_name(name: str) -> Optional[int]:
    key = name.strip().lower()
    if key in _MONTH_NAMES:
        return _MONTH_NAMES[key]
    for full, num in _MONTH_NAMES.items():
        if full.startswith(key) or key.startswith(full[:3]):
            return num
    return None


def _extract_ordinal_day_of_month_year(text: str) -> Optional[date]:
    for pattern in (_SUP_ORDINAL_DAY_RE, _PLAIN_ORDINAL_DAY_RE):
        m = pattern.search(text)
        if not m:
            continue
        day = int(m.group(1))
        mon = _month_from_english_name(m.group(2))
        year = int(m.group(3))
        if mon is None:
            continue
        try:
            return date(year, mon, day)
        except ValueError:
            continue
    return None


def extract_iso_date(text: str) -> Optional[date]:
    """Prefer statutory SH-7 headers, first YYYY-MM-DD, then ordinal 'DAY OF Month YYYY'."""
    sd = extract_statutory_notice_date(text)
    if sd is not None:
        return sd
    m = _ISO_DATE_RE.search(text)
    if m:
        return _date_from_yyyy_mm_dd(m.group(1))
    od = _extract_ordinal_day_of_month_year(text)
    if od is not None:
        return od
    return None


def parse_money_amount(s: str) -> Optional[int]:
    """Parse Indian-formatted rupee strings or plain integers."""
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"(?i)\bRs\.?\b", "", s).strip()
    s = s.replace("/-", "").replace("-/", "").replace("/", "").strip()

    m = re.search(r"([0-9][0-9,]*)", s)
    if not m:
        return None
    num = m.group(1)
    if "," not in num:
        try:
            return int(num)
        except ValueError:
            return None

    groups = [int(p) for p in num.split(",")]
    if len(groups) == 3:
        return groups[0] * 100_000 + groups[1] * 1_000 + groups[2]
    if len(groups) == 2:
        return groups[0] * 1_000 + groups[1]

    try:
        return int(num.replace(",", ""))
    except ValueError:
        return None


def safe_json_loads(s: str) -> Any:
    """Parse JSON, stripping optional markdown code fences."""
    if not s:
        raise ValueError("Empty JSON input")
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return json.loads(s)


_SHARE_LINE_RE = re.compile(
    r"(?m)^\s*\d+\)\s*(?P<class_name>.+?)\s*:\s*(?P<num>[0-9][0-9,]*)\s+.*?Shares\s+of\s+Rs\.?\s*(?P<nom>[0-9][0-9,]*)\s*/-?\s*each\s*\(total\s+Rs\.?\s*(?P<amount>[0-9][0-9,]*)\s*/-?\)\s*$",
    flags=re.IGNORECASE,
)


def parse_share_classes(text: str) -> list[dict[str, int | str]]:
    """Lines like: `1) Equity Shares: 1,00,000 ... of Rs. 10/- each (total Rs. ...)`"""
    out: list[dict[str, int | str]] = []
    for m in _SHARE_LINE_RE.finditer(text):
        class_name = m.group("class_name").strip()
        num = parse_money_amount(m.group("num"))
        nom = parse_money_amount(m.group("nom"))
        amt = parse_money_amount(m.group("amount"))
        if num is None or nom is None or amt is None:
            continue
        out.append(
            {
                "class_name": class_name,
                "num_shares": int(num),
                "nominal_value": int(nom),
                "amount": int(amt),
            }
        )
    return out


# --- Export ---

def ensure_parent_dir_exists(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def write_json(path: str, payload: Any) -> None:
    ensure_parent_dir_exists(path)
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_timeline_csv(timeline_output: "CapitalTimelineOutput", csv_path: str | Path) -> None:
    """One CSV row per `TimelineEntry` (auditable snapshot of timeline events)."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "Date",
        "Authorised Capital (Rs.)",
        "Change",
        "Delta (Rs.)",
        "Verified By",
        "Confidence",
        "Source Document",
        "Supporting EGM/AGM Events",
    ]

    def _date_to_str(v: object) -> str:
        if v is None:
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()  # type: ignore[no-any-return]
        return str(v)

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for entry in timeline_output.events:
            supporting = "; ".join(
                str(x.value)
                for x in getattr(entry, "egm_agm_events", [])
                if getattr(x, "value", None) is not None
            )
            writer.writerow(
                {
                    "Date": _date_to_str(entry.date.value),
                    "Authorised Capital (Rs.)": entry.authorised_capital.value,
                    "Change": entry.change.value,
                    "Delta (Rs.)": entry.delta.value,
                    "Verified By": "; ".join(entry.verified_by),
                    "Confidence": entry.confidence.value,
                    "Source Document": entry.source_document.value,
                    "Supporting EGM/AGM Events": supporting,
                }
            )
