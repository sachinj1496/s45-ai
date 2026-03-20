"""
Rule-based validation for per-event consistency and chronological capital chain.
"""

from __future__ import annotations

from typing import List, Tuple

from .models import CapitalChangeEvent, EventExtractionBundle, ValidationFinding, ValidationStatus


def _status_from(errors: list[str], warnings: list[str]) -> ValidationStatus:
    if errors:
        return "error"
    if warnings:
        return "warning"
    return "valid"


def validate_event(event: CapitalChangeEvent, bundle: EventExtractionBundle) -> ValidationFinding:
    """
    Cross-document checks: SH-7 vs MOA / board / EGM; PAS-3 vs authorised; required attachments when SH-7 exists.
    """
    errors: list[str] = []
    warnings: list[str] = []

    sh7 = bundle.sh7
    moa = bundle.moa
    board = bundle.board_resolution
    egm = bundle.egm_resolution
    unknown = bundle.unknown

    primary = sh7
    if primary is None or primary.new_authorised_capital is None:
        primary = unknown

    if primary is None or primary.new_authorised_capital is None:
        errors.append("Missing/insufficient authorised-capital extraction (SH-7/UNKNOWN).")
    else:
        if sh7 is None:
            warnings.append("SH-7 missing; using UNKNOWN extraction to generate authorised capital change.")

    if sh7 is not None:
        if board is None:
            errors.append("Missing BOARD resolution attachment for support validation.")
        if egm is None:
            errors.append("Missing EGM resolution attachment for support validation.")
        if event.moa_path is None or moa is None:
            errors.append("Missing MOA attachment (rule: SH-7 must match MOA final state).")

    if sh7 is not None and moa and sh7.new_authorised_capital is not None and moa.new_authorised_capital is not None:
        if sh7.new_authorised_capital != moa.new_authorised_capital:
            errors.append(
                f"SH-7 new authorised capital ({sh7.new_authorised_capital}) != MOA new authorised capital ({moa.new_authorised_capital})."
            )
    elif sh7 and moa:
        warnings.append("Unable to fully compare SH-7 vs MOA (missing extracted values).")

    if sh7 is not None and board and sh7.new_authorised_capital is not None and board.new_authorised_capital is not None:
        if sh7.new_authorised_capital != board.new_authorised_capital:
            errors.append(
                f"SH-7 new authorised capital ({sh7.new_authorised_capital}) != BOARD resolution proposal ({board.new_authorised_capital})."
            )

    if sh7 is not None and egm and sh7.new_authorised_capital is not None and egm.new_authorised_capital is not None:
        if sh7.new_authorised_capital != egm.new_authorised_capital:
            errors.append(
                f"SH-7 new authorised capital ({sh7.new_authorised_capital}) != EGM resolution approval ({egm.new_authorised_capital})."
            )

    if primary and len(primary.share_classes) < 2:
        warnings.append("Share class extraction returned fewer than 2 classes.")

    if bundle.pas3_issued_capital is not None and primary and primary.new_authorised_capital is not None:
        issued = bundle.pas3_issued_capital
        authorised = primary.new_authorised_capital
        if issued > authorised:
            errors.append(f"PAS-3 violation: issued capital {issued} > authorised capital {authorised}.")

    return ValidationFinding(status=_status_from(errors, warnings), errors=errors, warnings=warnings)


def validate_chain(sorted_events: List[Tuple[CapitalChangeEvent, EventExtractionBundle]]) -> ValidationFinding:
    """Enforce chronological consistency: previous new == next old."""
    errors: list[str] = []
    warnings: list[str] = []

    for i in range(1, len(sorted_events)):
        prev_ev, prev_bundle = sorted_events[i - 1]
        next_ev, next_bundle = sorted_events[i]

        prev_src = prev_bundle.sh7 or prev_bundle.unknown
        next_src = next_bundle.sh7 or next_bundle.unknown
        prev_new = prev_src.new_authorised_capital if prev_src else None
        next_old = next_src.old_authorised_capital if next_src else None

        if prev_new is None or next_old is None:
            warnings.append(f"Chain check skipped for {prev_ev.group_id} -> {next_ev.group_id} (missing extracted values).")
            continue

        if prev_new != next_old:
            errors.append(
                f"Inconsistent capital chain: previous event {prev_ev.group_id} new ({prev_new}) != next event {next_ev.group_id} old ({next_old})."
            )

    return ValidationFinding(status=_status_from(errors, warnings), errors=errors, warnings=warnings)
