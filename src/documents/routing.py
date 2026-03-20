"""Raw-folder → structured layout: pluggable format registry and ordered routing rules."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ..io.formats import FormatRegistry, get_default_format_registry
from ..models import DocumentClassification, DocumentType


@dataclass
class RoutingContext:
    structured_root: Path
    group_id: str
    classification: DocumentClassification
    text: str


class RoutingRule(ABC):
    """Chain-of-responsibility link: first rule that returns a path wins."""

    @abstractmethod
    def try_route(self, ctx: RoutingContext) -> Path | None:
        ...


class Sh7ClassificationRule(RoutingRule):
    def try_route(self, ctx: RoutingContext) -> Path | None:
        if ctx.classification.document_type != "SH7":
            return None
        return ctx.structured_root / "sh7" / f"sh7_group_{ctx.group_id}.txt"


def _looks_like_sh7(text: str) -> bool:
    t = text.lower()
    return (
        "form no. sh-7" in t
        or "form no. sh7" in t
        or ("notice to registrar" in t and "alteration of share capital" in t)
    )


def _looks_like_board_resolution_copy(text: str) -> bool:
    """Board-meeting resolution copy — must not be written into the SH-7 slot if misclassified."""
    t = text.lower()
    if _looks_like_sh7(text):
        return False
    if any(
        phrase in t
        for phrase in (
            "extra ordinary general meeting",
            "extraordinary general meeting",
            "passed at the extra ordinary",
            "passed at the extraordinary",
        )
    ):
        return False
    boardish = (
        "board meeting" in t
        or "meeting of the board" in t
        or "resolution (board meeting)" in t
    )
    return boardish and ("resolved that" in t or "certified true copy" in t)


class Sh7ContentRoutingRule(RoutingRule):
    """Prefer unmistakable SH-7 wording over an occasional wrong model label."""

    def try_route(self, ctx: RoutingContext) -> Path | None:
        if not _looks_like_sh7(ctx.text):
            return None
        return ctx.structured_root / "sh7" / f"sh7_group_{ctx.group_id}.txt"


class BoardResolutionContentRoutingRule(RoutingRule):
    """Keeps certified board copies out of `sh7/` when they are mislabeled as SH7."""

    def try_route(self, ctx: RoutingContext) -> Path | None:
        if not _looks_like_board_resolution_copy(ctx.text):
            return None
        return ctx.structured_root / "attachments" / f"board_resolution_group_{ctx.group_id}.txt"


def _looks_like_pas3(text: str) -> bool:
    t = text.lower()
    return (
        "pas-3" in t
        or "pas 3" in t
        or "form no. pas-3" in t
        or "form no. pas 3" in t
        or "return of allotment" in t
    )


def _pas3_destination_role(text: str) -> str:
    t = text.lower()
    if "form no. pas-3" in t or "form no. pas 3" in t or "form pas-3" in t or "pas-3 form" in t:
        return "pas3_form"
    if "list of allottees" in t or "table b" in t:
        return "list_of_allottees"
    return "board_resolution_allotment"


class Pas3ContentRoutingRule(RoutingRule):
    """Prefer PAS-3-shaped content over model label (BOARD_RESOLUTION mislabels)."""

    def try_route(self, ctx: RoutingContext) -> Path | None:
        if not _looks_like_pas3(ctx.text):
            return None
        role = _pas3_destination_role(ctx.text)
        pas3 = ctx.structured_root / "pas3"
        if role == "list_of_allottees":
            return pas3 / f"list_of_allottees_group_{ctx.group_id}.txt"
        if role == "pas3_form":
            return pas3 / f"pas3_form_group_{ctx.group_id}.txt"
        return pas3 / f"board_resolution_allotment_group_{ctx.group_id}.txt"


class DocumentTypePathRule(RoutingRule):
    def __init__(self, document_type: DocumentType, relative_parts: tuple[str, ...]) -> None:
        self.document_type = document_type
        self.relative_parts = relative_parts

    def try_route(self, ctx: RoutingContext) -> Path | None:
        if ctx.classification.document_type != self.document_type:
            return None
        return ctx.structured_root.joinpath(*self.relative_parts).with_name(
            self.relative_parts[-1].format(gid=ctx.group_id)
        )


def _default_raw_routing_rules() -> list[RoutingRule]:
    base = "attachments"
    return [
        Sh7ContentRoutingRule(),
        BoardResolutionContentRoutingRule(),
        Sh7ClassificationRule(),
        Pas3ContentRoutingRule(),
        DocumentTypePathRule("UNKNOWN", ("unknown", "unknown_group_{gid}.txt")),
        DocumentTypePathRule("BOARD_RESOLUTION", (base, "board_resolution_group_{gid}.txt")),
        DocumentTypePathRule("EGM_RESOLUTION", (base, "egm_resolution_group_{gid}.txt")),
        DocumentTypePathRule("MOA", (base, "moa_group_{gid}.txt")),
        DocumentTypePathRule("EGM_NOTICE", (base, "egm_notice_explanatory_group_{gid}.txt")),
    ]


class RawDataRoutingPipeline:
    """Template method: run ordered rules until one produces a destination path."""

    def __init__(
        self,
        rules: list[RoutingRule] | None = None,
        *,
        format_registry: FormatRegistry | None = None,
    ) -> None:
        self.rules = list(rules or _default_raw_routing_rules())
        self.format_registry = format_registry or get_default_format_registry()

    def route_tree(
        self,
        *,
        raw_root: str,
        structured_root: str,
        classify_document,
    ) -> None:
        raw_path = Path(raw_root)
        if not raw_path.exists():
            return

        out = Path(structured_root)
        (out / "sh7").mkdir(parents=True, exist_ok=True)
        (out / "attachments").mkdir(parents=True, exist_ok=True)
        (out / "pas3").mkdir(parents=True, exist_ok=True)
        (out / "unknown").mkdir(parents=True, exist_ok=True)

        for p in sorted(raw_path.rglob("*")):
            if not p.is_file():
                continue
            if not self.format_registry.is_supported(p):
                continue

            gid = group_id_from_raw_filename(str(p))
            if not gid:
                continue

            text = self.format_registry.read(p)
            classification = classify_document(text, source_path=str(p))
            # If the classifier marks a document as unclassifiable (confidence=0.0),
            # skip routing it. This lets users provide an ignore list for bad/outlier
            # inputs without breaking the pipeline.
            if getattr(classification, "confidence", 1.0) <= 0.0:
                continue
            ctx = RoutingContext(structured_root=out, group_id=gid, classification=classification, text=text)

            dest: Path | None = None
            for rule in self.rules:
                dest = rule.try_route(ctx)
                if dest is not None:
                    break

            if dest is None:
                continue

            dest.write_text(text, encoding="utf-8")


def group_id_from_raw_filename(raw_path: str) -> str | None:
    """Group id embedded in unstructured raw filenames, e.g. raw_g1_001.txt."""
    m = re.search(r"(?:g|group)(\d+)", Path(raw_path).name.lower())
    return m.group(1) if m else None


def route_raw_data_to_structured(
    *,
    raw_root: str = "data/raw_data",
    structured_root: str = "data",
    format_registry: FormatRegistry | None = None,
    routing_pipeline: RawDataRoutingPipeline | None = None,
    classify_document,
) -> None:
    """
    Bridge from flat/raw input to the structured layout expected by `load_dataset`.
    Pass a custom `RawDataRoutingPipeline` (rules + registry) to extend behaviour.
    """
    pipeline = routing_pipeline or RawDataRoutingPipeline(format_registry=format_registry)
    pipeline.route_tree(raw_root=raw_root, structured_root=structured_root, classify_document=classify_document)
