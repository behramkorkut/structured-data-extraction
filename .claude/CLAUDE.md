# Structured Data Extraction — Insurance Documents

## Project Overview
Extraction pipeline for structured data from APICIL insurance documents (IPID, guarantee tables, product sheets, pricing).
Built as Scenario 6 implementation for the Claude Certified Architect Foundations certification.

## Architecture
- `src/structured_extraction/` — Core extraction pipeline
- `tests/` — pytest test suite (mocked API calls, no cost)
- `scripts/` — CLI entry points for single doc, batch, and evaluation
- `data/insurance_docs/` — Source PDF documents (APICIL products)
- `data/labeled/` — Ground truth for validation and calibration
- `data/results/` — Extraction outputs

## Coding Standards
- Python 3.12+ with type hints on all function signatures
- Pydantic v2 models for all data structures
- Ruff for linting and formatting (line length: 100)
- Imports: stdlib → third-party → local, sorted by ruff

## Testing Conventions
- All tests use mocked API responses — zero API cost
- Use pytest fixtures for shared test data
- Test file naming: `test_<module>.py`
- Aim for both success paths and error/edge cases

## Key Design Decisions
- tool_use with JSON schemas for guaranteed schema-compliant extraction
- Nullable fields for information that may not exist in source documents
- Retry-with-error-feedback for validation failures (not for missing data)
- Field-level confidence scores for human review routing
- Message Batches API for non-blocking bulk processing
