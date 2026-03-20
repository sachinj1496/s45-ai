"""Hints for structured on-disk names (used when extending classification routing)."""

from __future__ import annotations

# Substrings in structured filenames that enable rule-based classification fast-path.
# Extend this tuple when you add new on-disk naming conventions.
DEFAULT_STRUCTURED_FILENAME_HINTS: tuple[str, ...] = (
    "sh7_group_",
    "board_resolution_group_",
    "egm_resolution_group_",
    "moa_group_",
    "egm_notice_explanatory_group_",
    "pas3_form_group_",
    "list_of_allottees_group_",
    "board_resolution_allotment_group_",
)
