"""
Authorised-share-capital pipeline: structured ingestion → LLM/rule extraction → validation → timeline + exports.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from .classifier import route_raw_data_to_structured
from .extractor import extract_capital_change, extract_pas3_issued_capital
from .ingestion import load_dataset, load_dataset_from_dirs
from .models import CapitalChangeEvent, EventExtractionBundle, ValidationFinding
from .timeline_builder import build_timeline
from .utils import setup_logging, write_json, write_timeline_csv
from .validator import validate_chain, validate_event

# --- Defaults & environment ---
DEFAULT_DATA_ROOT = "data"
DEFAULT_RAW_DATA_ROOT = "data/raw_data"
DEFAULT_OUTPUT_JSON = "outputs/capital_timeline.json"
ENV_ROUTE_FROM_RAW = "ROUTE_FROM_RAW"

DocumentTexts = dict[str, str]


# --- Extraction bundle (per event) ---
def _extract_bundle_for_event(ev: CapitalChangeEvent, texts: DocumentTexts) -> EventExtractionBundle:
    bundle = EventExtractionBundle()
    if ev.sh7_path:
        bundle.sh7 = extract_capital_change(texts[ev.sh7_path], "SH7")
    if ev.board_resolution_path:
        bundle.board_resolution = extract_capital_change(texts[ev.board_resolution_path], "BOARD_RESOLUTION")
    if ev.egm_resolution_path:
        bundle.egm_resolution = extract_capital_change(texts[ev.egm_resolution_path], "EGM_RESOLUTION")
    if ev.moa_path:
        bundle.moa = extract_capital_change(texts[ev.moa_path], "MOA")
    if ev.unknown_path:
        bundle.unknown = extract_capital_change(texts[ev.unknown_path], "UNKNOWN")

    issued_vals: list[int] = []
    for p in ev.pas3_paths:
        issued = extract_pas3_issued_capital(texts[p])
        if issued is not None:
            issued_vals.append(issued)
    bundle.pas3_issued_capital = max(issued_vals) if issued_vals else None
    return bundle


def _extract_all_bundles(events: list[CapitalChangeEvent], texts: DocumentTexts) -> dict[str, EventExtractionBundle]:
    return {ev.group_id: _extract_bundle_for_event(ev, texts) for ev in events}


# --- Sort & validate ---
def _sort_key_sh7_date(item: Tuple[CapitalChangeEvent, EventExtractionBundle]) -> tuple:
    bundle = item[1]
    d = None
    if bundle.sh7 and bundle.sh7.date:
        d = bundle.sh7.date
    elif bundle.unknown and bundle.unknown.date:
        d = bundle.unknown.date
    return (d is None, d)


def _validate_and_sort(
    events: list[CapitalChangeEvent],
    extraction_by_event: dict[str, EventExtractionBundle],
) -> tuple[list[Tuple[CapitalChangeEvent, EventExtractionBundle]], dict[str, dict], ValidationFinding]:
    findings_by_event: dict[str, dict] = {}
    for ev in events:
        finding = validate_event(ev, extraction_by_event[ev.group_id])
        findings_by_event[ev.group_id] = finding.model_dump()

    sorted_events = sorted(
        [(ev, extraction_by_event[ev.group_id]) for ev in events],
        key=_sort_key_sh7_date,
    )
    return sorted_events, findings_by_event, validate_chain(sorted_events)


# --- Load events & texts ---
def _ensure_events_loaded(
    data_root: str,
    *,
    import_sh7_dir: Optional[str],
    import_pas3_dir: Optional[str],
) -> Tuple[list[CapitalChangeEvent], DocumentTexts]:
    if import_sh7_dir and import_pas3_dir:
        return load_dataset_from_dirs(import_sh7_dir, import_pas3_dir)

    events, texts = load_dataset(data_root)
    if not events and Path(DEFAULT_RAW_DATA_ROOT).exists():
        route_raw_data_to_structured(raw_root=DEFAULT_RAW_DATA_ROOT, structured_root=data_root)
        events, texts = load_dataset(data_root)
    return events, texts


# --- Public API ---
def run_pipeline(
    data_root: str = DEFAULT_DATA_ROOT,
    output_path: str = DEFAULT_OUTPUT_JSON,
    *,
    import_sh7_dir: Optional[str] = None,
    import_pas3_dir: Optional[str] = None,
) -> dict:
    setup_logging()

    if os.getenv(ENV_ROUTE_FROM_RAW, "1").strip() == "1":
        route_raw_data_to_structured(raw_root=DEFAULT_RAW_DATA_ROOT, structured_root=data_root)

    events, texts = _ensure_events_loaded(
        data_root,
        import_sh7_dir=import_sh7_dir,
        import_pas3_dir=import_pas3_dir,
    )
    if not events:
        raise RuntimeError(f"No events found under {data_root}/sh7")

    extraction_by_event = _extract_all_bundles(events, texts)
    sorted_events, findings_by_event, chain_finding = _validate_and_sort(events, extraction_by_event)

    timeline_output = build_timeline(sorted_events)
    payload = timeline_output.model_dump()
    write_json(output_path, payload)

    csv_path = Path(output_path).with_suffix(".csv")
    write_timeline_csv(timeline_output, csv_path)

    return {
        "timeline": payload,
        "validation": {
            "per_event": findings_by_event,
            "chain": chain_finding.model_dump(),
        },
    }
