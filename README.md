# s45-ai

AI-assisted reconstruction of an **authorised share capital timeline** from Indian company compliance documents (SH-7, board / EGM resolutions, MOA, notices, PAS-3). The pipeline classifies and routes raw files, extracts structured amounts and dates (LLM with regex fallbacks), validates continuity, and writes JSON plus a per-event CSV.

## Requirements

- Python **3.10+**
- An **OpenAI API key** (or compatible endpoint via `OPENAI_API_BASE`)

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e .
```

Create a `.env` in the project root (optional but recommended):

```env
OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini
# OPENAI_API_BASE=https://api.openai.com/v1
```

## Run

From the repo root:

```bash
python main.py
```

Defaults:

| Setting | Default |
|--------|---------|
| Data root | `data/` (expects structured layout under `sh7/`, `attachments/`, `pas3/`, …) |
| Raw inputs | `data/raw_data/` (flat files; optional auto-route when no events are found) |
| JSON output | `outputs/capital_timeline.json` |
| CSV output | Same path with `.csv` extension |

**Always re-route from raw** before loading (overwrites/updates structured tree under `data/`):

```bash
ROUTE_FROM_RAW=1 python main.py
```

Programmatically, `run_pipeline()` lives in `src.pipeline` and accepts `data_root`, `output_path`, and optional `import_sh7_dir` / `import_pas3_dir` for ad-hoc folder imports.

## Data layout

- **`data/raw/`** — optional: same routing idea as `data/raw_data/` in code defaults.
- **Structured** (after routing or manual placement): `data/sh7/`, `data/attachments/`, `data/pas3/`, `data/unknown/`, with filenames like `sh7_group_<id>.txt` (see `src/documents/ingestion_profile.py`).
- Routing uses **content-aware rules** (e.g. SH-7 wording, board vs EGM) plus classifier output (`src/documents/routing.py`).

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for live LLM calls |
| `OPENAI_MODEL` | Model id (default `gpt-4o-mini`) |
| `OPENAI_API_BASE` | API base URL (default OpenAI) |
| `LLM_MAX_ATTEMPTS` | Retries on rate limits / transient errors (default `6`) |
| `ROUTE_FROM_RAW` | Set to `1` to route `data/raw_data` → structured `data/` on each run |
| `UNCLASSIFIED_DOCS` | Comma-separated basenames/paths to skip in classification |
| `UNCLASSIFIED_DOCS_FILE` | Path to a newline-separated ignore list |

## Tests

Integration tests call the real API:

```bash
python -m pytest
```

They expect `OPENAI_API_KEY` to be set (e.g. via `.env`); otherwise the suite fails fast with a clear message.

## Project layout

```
main.py                 # CLI entry
prompts/                # LLM prompts (classification, extraction)
src/
  pipeline.py           # Orchestration, exports
  classifier.py         # Document classification + raw routing entry
  extractor.py          # Capital / PAS-3 extraction
  timeline_builder.py   # Timeline + traceability
  validator.py          # Per-event + chain checks
  documents/            # Routing + ingestion rules + filename hints
  io/formats.py         # Pluggable readers (plain text today)
tests/
```

## License / status early version

Prototype quality (`v0.1.0`); validate outputs against source filings before relying on them for compliance.
