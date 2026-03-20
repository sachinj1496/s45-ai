"""Declarative rules mapping structured filenames to `CapitalChangeEvent` fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from ..models import CapitalChangeEvent

# Pydantic field names on `CapitalChangeEvent` for single-path slots.
_EventScalarField = Literal[
    "sh7_path",
    "board_resolution_path",
    "egm_resolution_path",
    "moa_path",
    "egm_notice_path",
    "unknown_path",
]


@dataclass(frozen=True)
class StructuredIngestionRule:
    """
    Declarative rule: files under `subdir` matching `filename_pattern` attach to an event.
    Add rules (or new `glob_pattern`) to support additional layouts / extensions without
    editing imperative grouping logic.
    """

    subdir: str
    filename_pattern: re.Pattern[str]
    field: _EventScalarField | Literal["pas3_paths"]
    glob_pattern: str = "*.txt"
    append_to_list: bool = False

    def __post_init__(self) -> None:
        if self.append_to_list and self.field != "pas3_paths":
            raise ValueError("append_to_list only valid for pas3_paths")
        if self.field == "pas3_paths" and not self.append_to_list:
            raise ValueError("pas3_paths rule must set append_to_list=True")


def _apply_rule(events: dict[str, CapitalChangeEvent], data_root: str, rule: StructuredIngestionRule) -> None:
    dir_path = Path(data_root) / rule.subdir
    if not dir_path.is_dir():
        return
    for p in dir_path.glob(rule.glob_pattern):
        if not p.is_file():
            continue
        m = rule.filename_pattern.search(p.name)
        if not m:
            continue
        gid = m.group("id")
        ev = events.setdefault(gid, CapitalChangeEvent(group_id=gid))
        path_str = str(p)
        if rule.append_to_list:
            ev.pas3_paths.append(path_str)
        else:
            setattr(ev, rule.field, path_str)


_STRUCTURED_INGESTION_RULES: tuple[StructuredIngestionRule, ...] = (
    StructuredIngestionRule("sh7", re.compile(r"sh7_group_(?P<id>\d+)\.txt$", re.IGNORECASE), "sh7_path"),
    StructuredIngestionRule(
        "attachments",
        re.compile(r"board_resolution_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "board_resolution_path",
    ),
    StructuredIngestionRule(
        "attachments",
        re.compile(r"egm_resolution_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "egm_resolution_path",
    ),
    StructuredIngestionRule("attachments", re.compile(r"moa_group_(?P<id>\d+)\.txt$", re.IGNORECASE), "moa_path"),
    StructuredIngestionRule(
        "attachments",
        re.compile(r"egm_notice_explanatory_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "egm_notice_path",
    ),
    StructuredIngestionRule(
        "pas3",
        re.compile(r"board_resolution_allotment_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "pas3_paths",
        append_to_list=True,
    ),
    StructuredIngestionRule(
        "pas3",
        re.compile(r"list_of_allottees_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "pas3_paths",
        append_to_list=True,
    ),
    StructuredIngestionRule(
        "pas3",
        re.compile(r"pas3_form_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "pas3_paths",
        append_to_list=True,
    ),
    StructuredIngestionRule(
        "unknown",
        re.compile(r"unknown_group_(?P<id>\d+)\.txt$", re.IGNORECASE),
        "unknown_path",
    ),
)


def group_events_by_rules(
    data_root: str,
    rules: Sequence[StructuredIngestionRule] | None = None,
) -> dict[str, CapitalChangeEvent]:
    events: dict[str, CapitalChangeEvent] = {}
    for rule in rules or _STRUCTURED_INGESTION_RULES:
        _apply_rule(events, data_root, rule)
    return events
