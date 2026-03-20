"""
Build `CapitalTimelineOutput` from validated, chronology-sorted events.

Sections: display formatting → shareholder register rows → bundle resolution → public `build_timeline`.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Tuple

from .models import (
    CapitalChangeEvent,
    CapitalTimelineOutput,
    EventExtractionBundle,
    ExtractedCapitalChange,
    ShareClass,
    ShareholderMeetingExtract,
    ShareholderMeetingTableRow,
    TimelineEntry,
    TraceableField,
)

# --- Numeric / display formatting (statutory register style) ---


def _change_label(old: int, new: int) -> str:
    if new > old:
        return "increase"
    if new < old:
        return "decrease"
    return "no_change"


def _format_indian_grouping(n: int) -> str:
    """Indian digit grouping (e.g. 110000000 → 11,00,00,000)."""
    if n < 0:
        return "-" + _format_indian_grouping(-n)
    s = str(int(n))
    if len(s) <= 3:
        return s
    last_three = s[-3:]
    rest = s[:-3]
    chunks: list[str] = []
    while len(rest) > 2:
        chunks.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        chunks.insert(0, rest)
    return ",".join(chunks) + "," + last_three


def _rupee_token(n: int) -> str:
    return _format_indian_grouping(n) if n >= 1000 else str(n)


def _format_share_class_segment(sc: ShareClass) -> str:
    ns = _rupee_token(sc.num_shares)
    nv = _rupee_token(sc.nominal_value)
    return f"{ns} {sc.class_name} of ₹ {nv} each"


def _particulars_line(amount: Optional[int], share_classes: list[ShareClass]) -> str:
    """Mirror statutory wording: ₹ … divided into …"""
    if amount is None:
        return "-"
    head = _format_indian_grouping(amount)
    if not share_classes:
        return f"₹ {head}"
    segments = [_format_share_class_segment(sc) for sc in share_classes]
    return f"₹ {head} divided into {' and '.join(segments)}"


def _format_meeting_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _str_or_none(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def _infer_agm_egm(ev: CapitalChangeEvent) -> str:
    if ev.egm_resolution_path:
        return "EGM"
    blob = " ".join(
        p or ""
        for p in (
            ev.sh7_path,
            ev.board_resolution_path,
            ev.moa_path,
            ev.egm_notice_path,
        )
    ).lower()
    if "agm" in blob and "egm" not in blob:
        return "AGM"
    if "annual general" in blob:
        return "AGM"
    return "-"


# --- Shareholder register row (LLM merge + fallbacks) ---


def _build_table_row_from_extraction(
    primary: ExtractedCapitalChange,
    ev: CapitalChangeEvent,
    *,
    prev_particulars_to: str | None,
    is_incorporation: bool,
) -> ShareholderMeetingTableRow:
    sm: ShareholderMeetingExtract | None = primary.shareholder_meeting

    computed_to = _particulars_line(primary.new_authorised_capital, primary.share_classes)
    to_line = _str_or_none(sm.particulars_to if sm else None) or computed_to
    change_summary = _str_or_none(sm.change_summary if sm else None)

    if is_incorporation:
        date_label = _str_or_none(sm.date_of_shareholders_meeting if sm else None) or "On incorporation"
        from_line = "-"
        meeting = _str_or_none(sm.agm_egm if sm else None) or "-"
    else:
        d = primary.date
        date_label = (
            _str_or_none(sm.date_of_shareholders_meeting if sm else None)
            or (_format_meeting_date(d) if d else "-")
        )
        if prev_particulars_to is not None:
            from_line = prev_particulars_to
        else:
            from_line = (
                _str_or_none(sm.particulars_from if sm else None)
                or (
                    _particulars_line(primary.old_authorised_capital, [])
                    if primary.old_authorised_capital is not None
                    else "-"
                )
            )
        meeting = _str_or_none(sm.agm_egm if sm else None) or _infer_agm_egm(ev)

    return ShareholderMeetingTableRow(
        date_of_shareholders_meeting=date_label,
        particulars_from=from_line,
        particulars_to=to_line,
        agm_egm=meeting,
        change_summary=change_summary,
    )


# --- Primary extraction source for an event timeline step ---


def _resolve_primary(
    ev: CapitalChangeEvent, bundle: EventExtractionBundle
) -> tuple[ExtractedCapitalChange, Optional[str], bool] | None:
    primary: ExtractedCapitalChange | None = bundle.sh7
    primary_path = ev.sh7_path
    primary_is_unknown = False
    if primary is None or primary.new_authorised_capital is None:
        primary = bundle.unknown
        primary_path = ev.unknown_path
        primary_is_unknown = True
    if primary is None:
        return None
    return (primary, primary_path, primary_is_unknown)


def _supporting_doc_paths(ev: CapitalChangeEvent, *, primary_is_unknown: bool) -> list[str]:
    if primary_is_unknown:
        return []
    docs: list[str] = []
    if ev.sh7_path:
        docs.append(ev.sh7_path)
    if ev.board_resolution_path:
        docs.append(ev.board_resolution_path)
    if ev.egm_resolution_path:
        docs.append(ev.egm_resolution_path)
    if ev.moa_path:
        docs.append(ev.moa_path)
    return docs


def _verified_doc_labels(bundle: EventExtractionBundle, new_cap: int) -> list[str]:
    labels: list[str] = []
    if bundle.moa and bundle.moa.new_authorised_capital == new_cap:
        labels.append("MOA")
    if bundle.board_resolution and bundle.board_resolution.new_authorised_capital == new_cap:
        labels.append("BOARD_RESOLUTION")
    if bundle.egm_resolution and bundle.egm_resolution.new_authorised_capital == new_cap:
        labels.append("EGM_RESOLUTION")
    return labels


def _egm_agm_trace_entries(
    ev: CapitalChangeEvent,
    primary_path: Optional[str],
    primary_is_unknown: bool,
    meeting_date_str: str,
) -> list[TraceableField]:
    entries: list[TraceableField] = []
    if ev.egm_resolution_path:
        entries.append(
            TraceableField(
                value=f"EGM resolution on {meeting_date_str}",
                source=ev.egm_resolution_path,
                supporting_docs=[ev.egm_resolution_path],
            )
        )
    if ev.egm_notice_path:
        entries.append(
            TraceableField(
                value=f"EGM notice / explanatory statement on {meeting_date_str}",
                source=ev.egm_notice_path,
                supporting_docs=[ev.egm_notice_path],
            )
        )
    entries.append(
        TraceableField(
            value=f"{_infer_agm_egm(ev)} on {meeting_date_str}",
            source=primary_path,
            supporting_docs=[primary_path] if primary_path and not primary_is_unknown else [],
        )
    )
    return entries


# --- Public API ---


def build_timeline(
    sorted_events: List[Tuple[CapitalChangeEvent, EventExtractionBundle]],
) -> CapitalTimelineOutput:
    entries: list[TimelineEntry] = []
    table_rows: list[ShareholderMeetingTableRow] = []
    prev_particulars_to: str | None = None

    for ev, bundle in sorted_events:
        resolved = _resolve_primary(ev, bundle)
        if resolved is None:
            continue
        primary, primary_path, primary_is_unknown = resolved

        authorised = primary.new_authorised_capital
        old = primary.old_authorised_capital
        supporting_docs = _supporting_doc_paths(ev, primary_is_unknown=primary_is_unknown)

        verified_by: list[str] = []
        if not primary_is_unknown and primary.new_authorised_capital is not None:
            verified_by = _verified_doc_labels(bundle, primary.new_authorised_capital)

        if authorised is None or old is None:
            delta = None
            change = None
        else:
            delta = authorised - old
            change = _change_label(old, authorised)

        meeting_date_part = primary.date.isoformat() if primary.date else "date-not-found"

        entries.append(
            TimelineEntry(
                date=TraceableField(
                    value=primary.date,
                    source=primary_path,
                    supporting_docs=[primary_path] if primary_path and not primary_is_unknown else [],
                ),
                authorised_capital=TraceableField(
                    value=authorised,
                    source=primary_path,
                    supporting_docs=list(supporting_docs),
                ),
                change=TraceableField(
                    value=change,
                    source=primary_path,
                    supporting_docs=[primary_path] if primary_path and not primary_is_unknown else [],
                ),
                delta=TraceableField(
                    value=delta,
                    source=primary_path,
                    supporting_docs=[primary_path] if primary_path and not primary_is_unknown else [],
                ),
                source_document=TraceableField(
                    value=primary_path,
                    source=primary_path,
                    supporting_docs=supporting_docs,
                ),
                verified_by=verified_by,
                confidence=TraceableField(
                    value=primary.confidence,
                    source=primary_path,
                    supporting_docs=[primary_path] if primary_path and not primary_is_unknown else [],
                ),
                egm_agm_events=_egm_agm_trace_entries(
                    ev, primary_path, primary_is_unknown, meeting_date_part
                ),
            )
        )

        is_incorporation = old is None and prev_particulars_to is None
        table_row = _build_table_row_from_extraction(
            primary,
            ev,
            prev_particulars_to=prev_particulars_to,
            is_incorporation=is_incorporation,
        )
        table_rows.append(table_row)
        prev_particulars_to = table_row.particulars_to

    return CapitalTimelineOutput(
        events=entries,
        shareholder_meeting_table=table_rows,
        generation_notes=[
            "Built from SH-7 extracted authorised share capital states; cross-validated against MOA and resolutions when available.",
            "shareholder_meeting_table: LLM `shareholder_meeting` on each extraction when present, else formatted from numbers; chained From uses prior row To.",
        ],
    )
