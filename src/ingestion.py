"""Load structured event skeletons from disk and read document text."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .documents.ingestion_profile import group_events_by_rules
from .models import CapitalChangeEvent
from .utils import read_text


def load_dataset(
    data_root: str = "data",
    *,
    layout_rules=None,
) -> tuple[list[CapitalChangeEvent], dict[str, str]]:
    """
    Returns:
      - list of event skeletons (grouped by SH-7 group id)
      - mapping of document path -> raw text

    Pass `layout_rules` to customise how paths map to `CapitalChangeEvent` fields
    (`StructuredIngestionRule` entries).
    """
    events_map = group_events_by_rules(data_root, layout_rules)

    all_paths: List[str] = []
    for ev in events_map.values():
        for p in [
            ev.sh7_path,
            ev.board_resolution_path,
            ev.egm_resolution_path,
            ev.moa_path,
            ev.egm_notice_path,
            ev.unknown_path,
            *ev.pas3_paths,
        ]:
            if p:
                all_paths.append(p)

    texts: Dict[str, str] = {}
    for path in all_paths:
        texts[path] = read_text(path)

    return list(events_map.values()), texts


def load_dataset_from_dirs(
    sh7_dir: str,
    pas3_dir: str,
    *,
    group_id: str = "1",
) -> tuple[list[CapitalChangeEvent], dict[str, str]]:
    """
    Import a single SH-7 event bundle from loosely named directories.

    Expected files (by keyword in filename; case-insensitive):
      - SH-7: `sh7` / `sh-7`
      - Board resolution (proposal): `board` + (`meeting` or `resolution`)
      - EGM resolution (approval): `egm` (but not `notice`)
      - MOA: `moa`
      - EGM notice (proposal): `notice` + (`egm` or `extra`)
    PAS-3:
      - Board resolution allotment: `board` + (`allotment` or `allot`)
      - List of allottees: `list` + `allottee` / `allottees`
      - PAS-3 form: `pas-3` / `pas3` + `form`
    """
    sh7_p = Path(sh7_dir)
    pas3_p = Path(pas3_dir)

    if not sh7_p.exists():
        raise FileNotFoundError(f"SH-7 directory not found: {sh7_dir}")
    if not pas3_p.exists():
        raise FileNotFoundError(f"PAS-3 directory not found: {pas3_dir}")

    def _iter_files(root: Path) -> list[Path]:
        return [p for p in root.glob("*") if p.is_file()]

    def _pick_one(paths: list[Path], predicate) -> Optional[Path]:
        for p in sorted(paths, key=lambda x: x.name.lower()):
            if predicate(p.name.lower()):
                return p
        return None

    sh7_files = _iter_files(sh7_p)
    pas3_files = _iter_files(pas3_p)

    sh7_file = _pick_one(sh7_files, lambda n: ("sh7" in n) or ("sh-7" in n))
    board_file = _pick_one(
        sh7_files,
        lambda n: ("board" in n) and (("meeting" in n) or ("resolution" in n)),
    )
    notice_file = _pick_one(sh7_files, lambda n: ("notice" in n) and ("egm" in n or "extra" in n))
    egm_file = _pick_one(
        sh7_files,
        lambda n: ("egm" in n) and ("notice" not in n) and ("explanatory" not in n),
    )
    moa_file = _pick_one(sh7_files, lambda n: "moa" in n)

    if sh7_file is None:
        raise FileNotFoundError(f"Could not find SH-7 file in: {sh7_dir}")

    pas3_board_file = _pick_one(
        pas3_files,
        lambda n: ("board" in n) and ("allot" in n) and ("resolution" in n or "allotment" in n or "shares" in n),
    )
    pas3_list_file = _pick_one(pas3_files, lambda n: ("list" in n) and ("allot" in n))
    pas3_form_file = _pick_one(pas3_files, lambda n: ("pas-3" in n or "pas3" in n) and ("form" in n))

    ev = CapitalChangeEvent(group_id=group_id)
    ev.sh7_path = str(sh7_file)
    ev.board_resolution_path = str(board_file) if board_file else None
    ev.egm_resolution_path = str(egm_file) if egm_file else None
    ev.moa_path = str(moa_file) if moa_file else None
    ev.egm_notice_path = str(notice_file) if notice_file else None

    for p in [pas3_board_file, pas3_list_file, pas3_form_file]:
        if p:
            ev.pas3_paths.append(str(p))

    texts: Dict[str, str] = {}
    all_paths = [ev.sh7_path, ev.board_resolution_path, ev.egm_resolution_path, ev.moa_path, ev.egm_notice_path, *ev.pas3_paths]
    for path in all_paths:
        if path:
            texts[path] = read_text(path)

    return [ev], texts
