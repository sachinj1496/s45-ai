"""Pluggable document layout: ingestion patterns, raw→structured routing, filename hints.

Prefer `classifier.route_raw_data_to_structured` for a wired-up entry point; use this package
directly when composing custom `FormatRegistry` / `RawDataRoutingPipeline` instances.
"""

from __future__ import annotations

from .filename_hints import DEFAULT_STRUCTURED_FILENAME_HINTS
from .ingestion_profile import StructuredIngestionRule, group_events_by_rules
from .routing import (
    DocumentTypePathRule,
    Pas3ContentRoutingRule,
    RawDataRoutingPipeline,
    RoutingContext,
    RoutingRule,
    Sh7ClassificationRule,
    group_id_from_raw_filename,
    route_raw_data_to_structured,
)

__all__ = [
    "DEFAULT_STRUCTURED_FILENAME_HINTS",
    "DocumentTypePathRule",
    "Pas3ContentRoutingRule",
    "RawDataRoutingPipeline",
    "RoutingContext",
    "RoutingRule",
    "Sh7ClassificationRule",
    "StructuredIngestionRule",
    "group_events_by_rules",
    "group_id_from_raw_filename",
    "route_raw_data_to_structured",
]
