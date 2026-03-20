import os

import pytest

from src.pipeline import run_pipeline
from src.classifier import classify_document
from src.classifier import route_raw_data_to_structured
from src.extractor import extract_capital_change
from src.ingestion import load_dataset


@pytest.fixture(scope="module", autouse=True)
def _require_openai_api_key():
    if not os.getenv("OPENAI_API_KEY", "").strip():
        pytest.fail("OPENAI_API_KEY is not set (export it or add it to `.env` in the project root).")


@pytest.fixture
def structured_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("structured_test")
    route_raw_data_to_structured(raw_root="data/raw_data", structured_root=str(root))
    return str(root)


def _get_text_by_suffix(texts: dict[str, str], suffix: str) -> str:
    # Ingestion returns Windows-style relative paths (e.g. `data\\sh7\\...`)
    normalized_suffix = suffix.replace("/", "\\")
    for k, v in texts.items():
        if k.endswith(normalized_suffix):
            return v
    raise KeyError(f"Text not found for suffix: {suffix}")


def test_classification_correctness(structured_root):
    _, texts = load_dataset(structured_root)

    # Group 1 core set
    assert classify_document(_get_text_by_suffix(texts, "sh7/sh7_group_1.txt")).document_type == "SH7"
    assert (
        classify_document(_get_text_by_suffix(texts, "attachments/board_resolution_group_1.txt")).document_type
        == "BOARD_RESOLUTION"
    )
    assert (
        classify_document(_get_text_by_suffix(texts, "attachments/egm_resolution_group_1.txt")).document_type
        == "EGM_RESOLUTION"
    )
    assert classify_document(_get_text_by_suffix(texts, "attachments/moa_group_1.txt")).document_type == "MOA"
    assert (
        classify_document(_get_text_by_suffix(texts, "attachments/egm_notice_explanatory_group_1.txt")).document_type
        == "EGM_NOTICE"
    )

    # Ambiguous/draft notice should still be EGM_NOTICE
    assert (
        classify_document(_get_text_by_suffix(texts, "attachments/egm_notice_explanatory_group_2.txt")).document_type
        == "EGM_NOTICE"
    )

    # PAS-3 bundle docs
    assert classify_document(_get_text_by_suffix(texts, "pas3/pas3_form_group_1.txt")).document_type == "PAS3"
    assert (
        classify_document(_get_text_by_suffix(texts, "pas3/list_of_allottees_group_4.txt")).document_type == "PAS3"
    )


def test_extraction_correctness(structured_root):
    _, texts = load_dataset(structured_root)

    g1 = extract_capital_change(_get_text_by_suffix(texts, "sh7/sh7_group_1.txt"), "SH7")
    assert g1.old_authorised_capital == 150_000
    assert g1.new_authorised_capital == 300_000
    assert str(g1.date) == "2018-03-22"
    assert len(g1.share_classes) == 2

    g2 = extract_capital_change(_get_text_by_suffix(texts, "sh7/sh7_group_2.txt"), "SH7")
    assert g2.old_authorised_capital == 300_000
    assert g2.new_authorised_capital == 600_000
    assert str(g2.date) == "2021-06-30"

    g3 = extract_capital_change(_get_text_by_suffix(texts, "sh7/sh7_group_3.txt"), "SH7")
    # Capital reduction within group3
    assert g3.old_authorised_capital == 650_000
    assert g3.new_authorised_capital == 400_000
    assert str(g3.date) == "2023-04-28"

    g4 = extract_capital_change(_get_text_by_suffix(texts, "sh7/sh7_group_4.txt"), "SH7")
    # Missing MOA in group4 will be handled in validation tests.
    assert g4.old_authorised_capital == 400_000
    assert g4.new_authorised_capital == 200_000
    assert str(g4.date) == "2024-09-30"


def test_validation_edge_cases(structured_root):
    output_path = os.path.join(structured_root, "capital_timeline.json")
    result = run_pipeline(structured_root, output_path)
    per_event = result["validation"]["per_event"]
    chain = result["validation"]["chain"]

    # Missing MOA + PAS-3 violation should be detected in group4
    assert per_event["4"]["status"] == "error"
    joined_errors_4 = " ".join(per_event["4"]["errors"])
    assert "Missing MOA attachment" in joined_errors_4
    assert "PAS-3 violation" in joined_errors_4

    # Chain inconsistency should be detected between group 2 and group 3
    assert chain["status"] == "error"
    joined_chain_errors = " ".join(chain["errors"])
    assert "2 new (600000) != next event 3 old (650000)" in joined_chain_errors

    assert per_event["1"]["status"] == "valid"
