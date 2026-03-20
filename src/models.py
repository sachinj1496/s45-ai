"""Pydantic domain models: classification, extraction bundles, timeline, validation."""

from __future__ import annotations

from datetime import date as Date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


DocumentType = Literal["SH7", "BOARD_RESOLUTION", "EGM_RESOLUTION", "MOA", "EGM_NOTICE", "PAS3", "UNKNOWN"]
Authority = Literal["high", "medium", "low", "unknown"]
EventType = Literal["capital_change", "share_allotment", "proposal", "unknown"]
ValidationStatus = Literal["valid", "warning", "error"]


class DocumentClassification(BaseModel):
    document_type: DocumentType
    authority: Authority
    event: EventType
    confidence: float = Field(ge=0.0, le=1.0)


class ShareClass(BaseModel):
    class_name: str
    num_shares: int
    nominal_value: int
    amount: int


class ShareholderMeetingExtract(BaseModel):
    """
    Optional registrar-style row fragment produced by the LLM alongside numeric extraction.
    Used to populate shareholder_meeting_table; fields may be partial—timeline falls back to formatting.
    """

    model_config = ConfigDict(extra="ignore")

    date_of_shareholders_meeting: Optional[str] = None
    particulars_from: Optional[str] = None
    particulars_to: Optional[str] = None
    agm_egm: Optional[str] = None
    # Short prose describing the change (e.g. for audit trail); optional.
    change_summary: Optional[str] = None


class ExtractedCapitalChange(BaseModel):
    model_config = ConfigDict(extra="ignore")

    old_authorised_capital: Optional[int] = None
    new_authorised_capital: Optional[int] = None
    date: Optional[Date] = None
    share_classes: list[ShareClass] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    shareholder_meeting: Optional[ShareholderMeetingExtract] = None


class TraceableField(BaseModel):
    value: Any = None
    source: Optional[str] = None
    supporting_docs: list[str] = Field(default_factory=list)


class ValidationFinding(BaseModel):
    status: ValidationStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CapitalChangeEvent(BaseModel):
    group_id: str
    sh7_path: Optional[str] = None
    board_resolution_path: Optional[str] = None
    egm_resolution_path: Optional[str] = None
    moa_path: Optional[str] = None
    egm_notice_path: Optional[str] = None
    unknown_path: Optional[str] = None
    pas3_paths: list[str] = Field(default_factory=list)


class EventExtractionBundle(BaseModel):
    sh7: Optional[ExtractedCapitalChange] = None
    board_resolution: Optional[ExtractedCapitalChange] = None
    egm_resolution: Optional[ExtractedCapitalChange] = None
    moa: Optional[ExtractedCapitalChange] = None
    # PAS-3 uses issued capital (paid-up) not authorised capital changes
    unknown: Optional[ExtractedCapitalChange] = None
    pas3_issued_capital: Optional[int] = None


class TimelineEntry(BaseModel):
    date: TraceableField = Field(default_factory=TraceableField)
    authorised_capital: TraceableField = Field(default_factory=TraceableField)
    change: TraceableField = Field(default_factory=TraceableField)
    delta: TraceableField = Field(default_factory=TraceableField)
    source_document: TraceableField = Field(default_factory=TraceableField)
    verified_by: list[str] = Field(default_factory=list)
    confidence: TraceableField = Field(default_factory=TraceableField)
    # Human-readable event references derived from attachments (e.g., EGM resolution/notice).
    # Each item keeps traceability to the underlying source document path.
    egm_agm_events: list[TraceableField] = Field(default_factory=list)


class ShareholderMeetingTableRow(BaseModel):
    """
    Registrar-style “Date / Particulars (From → To) / AGM-EGM” row (JSON projection of the statutory table).
    """

    date_of_shareholders_meeting: str
    particulars_from: str
    particulars_to: str
    agm_egm: str
    change_summary: Optional[str] = None


class CapitalTimelineOutput(BaseModel):
    events: list[TimelineEntry]
    shareholder_meeting_table: list[ShareholderMeetingTableRow] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)

