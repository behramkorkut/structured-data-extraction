# Structured Data Extraction — Insurance Documents

A production-grade extraction pipeline for structured data from French insurance documents (APICIL), built as a hands-on implementation of **Scenario 6** from the [Claude Certified Architect Foundations](https://claudecertifications.com/claude-certified-architect/exam-guide) certification exam.

The system extracts structured information from unstructured insurance PDFs (IPIDs, guarantee tables, product sheets), validates output using JSON schemas and semantic rules, implements retry-with-error-feedback loops, routes low-confidence extractions to human review, and supports batch processing via the Message Batches API.

> **Part of a certification prep series:**
>
> * Scenario 1 — [Customer Support Agent](https://github.com/behramkorkut/customer-support-agent)
> * Scenario 3 — [Multi-Agent Research System](https://github.com/behramkorkut/multi-agent-research)
> * **Scenario 6 — Structured Data Extraction** ← you are here

---

## Architecture
```
    Insurance PDFs (APICIL)
    IPID / Guarantee Tables / Product Sheets
                │
                ▼
┌──────────────────────────────────┐
│        DOCUMENT LOADER           │
│   pdfplumber text extraction     │
│   Auto-detect type & product     │
│   line from filename patterns    │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│     EXTRACTION (Claude API)      │
│                                  │
│  tool_use + JSON schema          │
│  ┌─ extract_ipid                 │
│  └─ extract_guarantee_table      │
│                                  │
│  tool_choice:                    │
│    known type → forced selection │
│    unknown   → "any"             │
│                                  │
│  + few-shot examples             │
│  + system prompt with rules      │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│     PYDANTIC VALIDATION          │
│                                  │
│  Semantic checks:                │
│  • Internal consistency          │
│  • Value plausibility (0-600%)   │
│  • Completeness (categories)     │
│  • "other" enum has detail       │
│  • comfort_pack flag ↔ options   │
└───────────────┬──────────────────┘
                │
          is_valid?
          ├── YES ──────────────────────┐
          └── NO                        │
                │                       │
                ▼                       │
┌──────────────────────────────────┐    │
│   RETRY WITH ERROR FEEDBACK      │    │
│                                  │    │
│  Prompt includes:                │    │
│  1. Specific validation errors   │    │
│  2. Previous extraction (JSON)   │    │
│  3. Original document            │    │
│                                  │    │
│  Skip retry if errors are        │    │
│  MISSING_CONTENT (not retryable) │    │
│  Max 2 retries (safety net)      │    │
└───────────────┬──────────────────┘    │
                │                       │
                ▼◄──────────────────────┘
┌──────────────────────────────────┐
│   CONFIDENCE ROUTING             │
│                                  │
│  Per-field confidence scores     │
│  HIGH    → AUTO_ACCEPT           │
│  MEDIUM  → HUMAN_REVIEW          │
│  LOW     → HUMAN_REVIEW (urgent) │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│   INDEPENDENT QUALITY REVIEW     │
│                                  │
│  Separate Claude instance        │
│  (no shared context with         │
│   extraction — avoids            │
│   confirmation bias)             │
│                                  │
│  Checks for:                     │
│  • Hallucination                 │
│  • Misclassification             │
│  • Missed information            │
│  • Inaccuracy                    │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│   BATCH PROCESSING               │
│   Message Batches API            │
│   50% cost savings               │
│   custom_id correlation          │
│   Failed item resubmission       │
└──────────────────────────────────┘
```


---

## Key Concepts Implemented

### Guaranteed Schema Compliance via `tool_use` (Task 4.3)

Extraction uses Claude's `tool_use` with JSON schemas derived from Pydantic models. This eliminates JSON syntax errors through constrained decoding — Claude can only generate tokens that match the schema grammar. Two extraction tools are defined with detailed descriptions that clearly differentiate their purpose, including negative guidance ("Do NOT use for...").

**`tool_choice` strategy:**

| Document Type | `tool_choice` | Why |
|---|---|---|
| `ipid` (detected) | `{"type": "tool", "name": "extract_ipid"}` | Forced selection — we know the type |
| `guarantee_table` (detected) | `{"type": "tool", "name": "extract_guarantee_table"}` | Forced selection |
| `unknown` | `{"type": "any"}` | Claude must call a tool but chooses which |
| Never used | `"auto"` | Risk of Claude returning prose instead of structured data |
**Exam reference:** Domain 4, Task 4.3

### Nullable Fields Prevent Hallucination (Task 4.3)

When source documents may not contain certain information, schema fields are `Optional` (nullable). This gives Claude an honest exit — returning `null` instead of fabricating a plausible value. For example, the IPID for "Garantie Hospitalisation" doesn't mention Loi Madelin, so `madelin_eligible` correctly returns `null` rather than a guessed `True` or `False`.

```python
# BAD — required field forces Claude to fabricate a value
madelin_eligible: bool  # Claude: True (hallucination!)

# GOOD — nullable field allows honest "not found"
madelin_eligible: bool | None = None  # Claude: null (correct)
```
**Exam reference: Domain 4, Task 4.3**

### Enum with "other" + Detail Pattern (Task 4.3)

Coverage categories and reimbursement types use enums with an OTHER value plus a detail string field. This prevents silent misclassification when Claude encounters a category not in the predefined list (e.g., "cure thermale"). Validation rules enforce that category_detail must be populated when category == "other".
**Exam reference: Domain 4, Task 4.3**

### Semantic Validation Layer (Task 4.4)

JSON schemas eliminate syntax errors but not semantic errors. The validation layer catches what schemas cannot:

| Rule | Category | Example |
|------|----------|---------|
| comfort_pack flag ↔ options | INTERNAL_CONSISTENCY | has_comfort_pack: true but comfort_pack_options: null |
| Percentage range 0-600% | VALUE_PLAUSIBILITY | percentage: 700.0 (implausible for insurance) |
| Coverage category diversity | COMPLETENESS | Only 1 category found in a multi-category table |
| "other" has detail | INTERNAL_CONSISTENCY | category: "other" without category_detail |
| Responsible contract exclusions | INTERNAL_CONSISTENCY | responsible_contract: true without regulatory exclusions |
**Exam reference: Domain 4, Task 4.4**

### Retry-with-Error-Feedback (Task 4.4)

When validation fails, the retry prompt includes three elements: (1) the specific validation errors with field paths, (2) the previous extraction as JSON, and (3) the original document. This enables targeted self-correction rather than blind re-extraction.

Critically, retries are skipped when all errors are MISSING_CONTENT — information simply absent from the source document cannot be fixed by re-extraction.

**Exam reference: Domain 4, Task 4.4**

### Few-Shot Examples for Varied Formats (Task 4.2)

Insurance documents use diverse reimbursement formats ("100% BR - SS", "30 € / séance 5 séances max", "Zéro reste à charge"). Few-shot examples demonstrate how to normalize these into a unified schema. Each example includes reasoning that teaches Claude the decision logic — not just input→output mapping — enabling generalization to novel formats.

Examples also demonstrate critical behaviors: returning null for missing data, handling empty table cells as "not covered at this level", and distinguishing regulatory exclusions from product design exclusions.

**Exam reference: Domain 4, Task 4.2**

### Independent Quality Review (Task 4.6)

A separate Claude instance reviews extractions without the extraction session's reasoning context. This avoids confirmation bias — the reviewer doesn't know why the extractor made its choices, so it evaluates objectively. The reviewer checks for hallucination, misclassification, missed information, and inaccuracy using a dedicated submit_review tool with forced selection.

**Exam reference: Domain 4, Task 4.6**

### Field-Level Confidence and Human Review Routing (Task 5.5)

Claude assigns per-field confidence scores during extraction. These drive routing decisions: HIGH → auto-accept, MEDIUM/LOW → human review. The AccuracyTracker monitors accuracy by document type AND by field, preventing aggregate metrics (e.g., 97% overall) from masking poor performance on specific fields or document types. Stratified random sampling ensures quality measurement covers all document type segments proportionally.

**Exam reference: Domain 5, Task 5.5**

### Message Batches API for Cost-Efficient Processing (Task 4.5)

Batch processing offers 50% cost savings for latency-tolerant workloads (overnight document processing). Each document is an independent single-turn extraction — compatible with the Batches API's limitation of no multi-turn tool calling. Failed items are identified by custom_id for targeted resubmission. SLA calculation accounts for the 24-hour maximum processing window.

**Exam reference: Domain 4, Task 4.5**

## Anti-Patterns Avoided
| # | Anti-Pattern | What We Do Instead |
|---|-------------|---------------------|
| 1 | tool_choice: "auto" risking prose output | Forced selection or "any" — always structured |
| 2 | Required fields for optional data → hallucination | Nullable fields with Optional[T] = None |
| 3 | Blind retry without feedback | Retry prompt includes specific validation errors |
| 4 | Retry on missing content | has_retryable_errors skips non-retryable errors |
| 5 | Same-session self-review | Independent instance with separate system prompt |
| 6 | Aggregate-only accuracy | Per-field, per-document-type accuracy tracking |
| 7 | Generic error categories | Structured ValidationErrorCategory enum |
| 8 | Vague prompts ("extract data") | Explicit criteria + few-shot with reasoning |
| 9 | Closed enums forcing misclassification | OTHER + detail pattern for extensibility |
| 10 | Single-pass for all validation | Syntax (schema) + semantic (rules) layered checks |

## Project Structure
```bash

structured-data-extraction/
├── src/
│   └── structured_extraction/
│       ├── __init__.py           # Public API exports
│       ├── schemas.py            # Pydantic models + JSON schemas (IPID, BG)
│       ├── extraction.py         # Core extraction via tool_use
│       ├── validation.py         # Semantic validation rules
│       ├── retry.py              # Retry-with-error-feedback loop
│       ├── few_shot.py           # Few-shot examples for varied formats
│       ├── confidence.py         # Field-level confidence + review routing
│       ├── review.py             # Independent Claude instance quality review
│       ├── batch.py              # Message Batches API integration
│       ├── metrics.py            # Pipeline metrics and reporting
│       └── document_loader.py    # PDF text extraction + type detection
├── tests/
│   ├── test_schemas.py           # 40 tests — models, enums, JSON schema gen
│   ├── test_document_loader.py   # 29 tests — type detection, file loading
│   ├── test_extraction.py        # 31 tests — tool choice, response parsing
│   ├── test_validation.py        # 29 tests — semantic rules, feedback format
│   ├── test_retry.py             # 15 tests — retry loop, audit trail
│   ├── test_few_shot.py          # 12 tests — example structure, formatting
│   ├── test_confidence.py        # 25 tests — routing, accuracy, sampling
│   ├── test_review.py            # 15 tests — independent review, API mock
│   ├── test_batch.py             # 10 tests — batch prep, result parsing, SLA
│   └── test_metrics.py           #  5 tests — metrics calculation
├── scripts/
│   ├── extract_single.py         # Single document extraction demo
│   ├── extract_batch.py          # Batch processing demo
│   └── run_evaluation.py         # Run against labeled set + metrics
├── data/
│   ├── insurance_docs/           # Source APICIL PDFs (7 product lines)
│   ├── labeled/                  # Ground truth for calibration
│   └── results/                  # Extraction outputs
├── .claude/
│   ├── CLAUDE.md                 # Project instructions for Claude Code
│   └── rules/
│       └── testing.md            # Path-scoped testing conventions
├── docs/
│   └── JOURNALDEBORD.md          # Development journal
├── pyproject.toml
├── Makefile
└── .env.example
```

## Getting Started
### Prerequisites

    Python 3.12+
    uv package manager
    An Anthropic API key (for live extraction)

### Installation
```bash 
git clone https://github.com/behramkorkut/structured-data-extraction.git
cd structured-data-extraction
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
uv sync --extra dev

#Run the Tests (no API key needed)

uv run pytest tests/ -v --tb=short

#All 211 tests run against mocked API responses — zero cost, fully deterministic.

#Run the Pipeline Demo

# Dry run (no API key needed — shows pipeline structure)
uv run python scripts/extract_single.py

# Live extraction (requires API key)
export ANTHROPIC_API_KEY=sk-ant-...
uv run python scripts/extract_single.py

# Extract a specific PDF
uv run python scripts/extract_single.py data/insurance_docs/API\ SANTE/IPID/SP24FCR0103\ IPID\ API\ Santé\ Equilibre\ -\ MAJ-\ 052024.pdf
```

### Makefile Commands
```bash
make install    # uv sync --extra dev
make test       # Run all 211 tests
make test-cov   # Tests with coverage report
make lint       # Ruff linting
make format     # Ruff formatting
make run-single # Run single document extraction
make run-batch  # Run batch processing
make run-eval   # Run evaluation against labeled set
make clean      # Remove build artifacts
```

## Document Types Supported

| Type | Pattern | Fields Extracted |
|------|---------|------------------|
| IPID | Insurance Product Information Document | Product name, insurer, coverage, exclusions, obligations, geographic scope |
| Guarantee Table (Barème) | Tabular benefit-by-benefit reimbursement | Benefits, reimbursement levels, comfort packs, footnotes, lexicon |
| Product Sheet | Fiche produit | (extensible — add schema) |
| Pricing | Cotisations/Tarifs | (extensible — add schema) |
| Reimbursement Example | Exemples de remboursement | (extensible — add schema) |

## APICIL Product Lines Detected

API Santé Equilibre, API Santé Sérénité, APICIL Essentio, APICIL Accident, APICIL Protection Décès, APICIL Tandem, Garantie Hospitalisation.

## Exam Domain Coverage
| Domain 	| Weight 	| Where It's Implemented|
|-----------|-----------|-----------------------|
| D4: Prompt Engineering & Structured Output 	| 20% 	| extraction.py (tool_use, tool_choice), schemas.py (nullable, enums), few_shot.py, validation.py (semantic rules), retry.py (error feedback), batch.py (Batches API), review.py (multi-instance)|
| D5: Context Management & Reliability 	| 15% 	| confidence.py (field-level scoring, stratified sampling, accuracy tracking), review.py (independent review routing), metrics.py (per-type breakdown)|

## Key Design Decisions & Tradeoffs

1. tool_use vs output_config.format for Structured Output

Decision: Use tool_use with JSON schemas rather than the newer output_config.format (JSON mode).

Why: tool_use is the approach explicitly tested in the CCA-F exam and is the most battle-tested method. It also allows multiple extraction schemas in a single call (IPID vs guarantee table), with Claude selecting via tool_choice. JSON mode would require separate configurations per document type.

Tradeoff: tool_use has schema complexity limits (24 optional parameters max). Our schemas fit within these limits, but very complex schemas would need splitting.

2. Pydantic Models as Single Source of Truth

Decision: Pydantic models define the schema once, generating both Python validation and JSON schemas for Claude.

Why: Eliminates drift between the schema Claude sees and the validation code. When we add a field to the Pydantic model, Claude's extraction schema updates automatically.

Tradeoff: Pydantic's JSON schema output includes $ref and $defs which add token overhead. For very token-sensitive deployments, hand-crafted schemas would be leaner.

3. Semantic Validation as Separate Layer (not Schema Constraints)

Decision: Business rules (percentage ranges, consistency checks) are enforced in Python code, not in JSON schema constraints.

Why: JSON schemas can express minimum/maximum but Claude's structured outputs strip unsupported constraints. Python validation gives us unlimited expressiveness: cross-field consistency, conditional rules, plausibility checks.

Tradeoff: Two validation passes (schema + semantic) instead of one. But the first pass is free (constrained decoding) and the second is fast (pure Python, no API calls).

4. Conservative Confidence Routing

Decision: Any field below HIGH confidence triggers human review for the entire extraction.

Why: In insurance, incorrect data has regulatory consequences. False acceptance is worse than unnecessary review. As confidence calibration improves with labeled data, thresholds can be relaxed.

Tradeoff: Early in deployment, most extractions will go to human review until confidence is calibrated. This is intentional — it's the safe starting point.

## Tech Stack

    Python 3.12+ with type hints
    Anthropic SDK (anthropic>=0.100.0) — Claude API client
    Pydantic v2 — data validation, JSON schema generation
    pdfplumber — PDF text extraction
    pytest — 211 tests with mocked API calls
    uv — fast Python package manager
    Ruff — linting and formatting

## Related Work

    Customer Support Agent (Scenario 1) — single-agent agentic loop with hooks, tool_use, and escalation
    Multi-Agent Research (Scenario 3) — coordinator-subagent orchestration with provenance tracking
    CCA-F Exam Guide — official exam domains and scenarios

## License

MIT

## Author

Behram Korkut — Data Engineer, 2026 






