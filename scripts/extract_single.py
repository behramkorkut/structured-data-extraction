"""
Demo script: extract structured data from a single insurance document.

Demonstrates the full pipeline:
1. Load document (PDF or text)
2. Extract with tool_use (forced selection or "any")
3. Validate (semantic checks)
4. Retry with error feedback (if validation fails)
5. Score confidence per field
6. Route for human review (if low confidence)
7. Independent quality review (separate Claude instance)

Usage:
    uv run python scripts/extract_single.py [path_to_document]

Without arguments, runs a built-in demo with sample text.
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.structured_extraction.document_loader import load_document, detect_document_type
from src.structured_extraction.extraction import TokenUsage
from src.structured_extraction.document_loader import (
    is_extraction_supported,
    get_unsupported_reason,
)
from src.structured_extraction.retry import extract_with_retry, RetryConfig
from src.structured_extraction.validation import validate_extraction
from src.structured_extraction.confidence import route_for_review
from src.structured_extraction.metrics import PipelineMetrics


# ---------------------------------------------------------------------------
# Sample document for demo (no API key needed for dry run)
# ---------------------------------------------------------------------------

SAMPLE_IPID_TEXT = """Assurance Complémentaire Santé
Document d'information sur le produit d'assurance

APICIL Mutuelle, mutuelle immatriculée en France au répertoire SIRENE sous le n° 302 927 553

Produit : API Santé Équilibre

De quel type d'assurance s'agit-il ?
Le produit d'assurance complémentaire santé API Santé Équilibre est destiné à rembourser
tout ou partie des frais de santé restant à la charge de l'assuré(e).
Peuvent adhérer toutes personnes physiques âgées de 16 ans minimum.
Le produit respecte les conditions légales des contrats responsables 100 % SANTÉ
et est éligible à la fiscalité Loi Madelin.

Qu'est-ce qui est assuré ?
Soins courants : consultations généralistes et spécialistes, actes techniques médicaux,
honoraires paramédicaux, médicaments, matériel médical.
Hospitalisation : honoraires chirurgicaux, forfait journalier hospitalier, chambre particulière.
Optique : verres et montures, lentilles, chirurgie réfractive (selon niveau).
Dentaire : soins dentaires, prothèses, orthodontie, implantologie (selon niveau).
Aides auditives : appareils auditifs, piles acoustiques.

Qu'est-ce qui n'est pas assuré ?
- Les soins reçus en dehors de la période de validité du contrat
- La chirurgie esthétique non prise en charge par la Sécurité sociale
- Les indemnités versées en complément de la Sécurité sociale en cas d'arrêt de travail

Y-a-t-il des exclusions à la couverture ?
La participation forfaitaire sur les consultations médicales et actes de biologie médicale.
La franchise sur les médicaments, actes paramédicaux et transports sanitaires.
La majoration du ticket modérateur hors parcours de soins.

Où suis-je couvert(e) ?
En France métropolitaine (dont la Corse) et dans les DROM.
À l'étranger, remboursement sur la base du tarif de convention SS française.

Réf. : SP24/FCR0103 – MAJ 05/2024
"""


def run_demo_dry_run():
    """Run the pipeline demo without API calls (shows pipeline structure)."""
    print("=" * 60)
    print("STRUCTURED DATA EXTRACTION PIPELINE — DRY RUN DEMO")
    print("=" * 60)
    print()

    # Step 1: Document detection
    source_file = "IPID API Santé Equilibre.txt"
    doc_type = detect_document_type(source_file)
    print(f"[1/6] Document detection")
    print(f"      File: {source_file}")
    print(f"      Detected type: {doc_type}")
    print(f"      Text length: {len(SAMPLE_IPID_TEXT):,} chars")
    print()

    # Step 2: Tool choice strategy
    from src.structured_extraction.extraction import get_tool_choice
    tool_choice = get_tool_choice(doc_type)
    print(f"[2/6] Tool choice strategy")
    print(f"      Document type '{doc_type}' → tool_choice: {tool_choice}")
    print(f"      Mode: FORCED SELECTION (document type is known)")
    print()

    # Step 3: Show what the API call would look like
    from src.structured_extraction.extraction import ALL_EXTRACTION_TOOLS, EXTRACTION_SYSTEM_PROMPT
    print(f"[3/6] Extraction (API call — skipped in dry run)")
    print(f"      Model: claude-haiku-4-5")
    print(f"      Tools: {[t['name'] for t in ALL_EXTRACTION_TOOLS]}")
    print(f"      System prompt: {len(EXTRACTION_SYSTEM_PROMPT)} chars")
    print(f"      ⚠️  Set ANTHROPIC_API_KEY to run real extraction")
    print()

    # Step 4: Show validation rules
    print(f"[4/6] Validation rules that would apply:")
    print(f"      ✓ covered_items not empty (COMPLETENESS)")
    print(f"      ✓ regulatory exclusions present if responsible contract (CONSISTENCY)")
    print(f"      ✓ 'other' category has detail string (CONSISTENCY)")
    print(f"      ✓ coverage categories diverse (COMPLETENESS)")
    print(f"      ✓ Madelin eligibility plausible for insurance type (PLAUSIBILITY)")
    print()

    # Step 5: Show retry config
    config = RetryConfig()
    print(f"[5/6] Retry configuration")
    print(f"      Max retries: {config.max_retries}")
    print(f"      Retry only on retryable errors: {config.retry_only_on_retryable}")
    print(f"      Non-retryable: MISSING_CONTENT (info absent from doc)")
    print()

    # Step 6: Show confidence routing
    print(f"[6/6] Confidence routing")
    print(f"      HIGH confidence → AUTO_ACCEPT")
    print(f"      MEDIUM confidence → HUMAN_REVIEW (verify against source)")
    print(f"      LOW confidence → HUMAN_REVIEW (likely incorrect)")
    print(f"      NOT_FOUND → flagged (field absent from document)")
    print()

    print("=" * 60)
    print("To run with real API calls:")
    print("  1. cp .env.example .env")
    print("  2. Add your ANTHROPIC_API_KEY to .env")
    print("  3. uv run python scripts/extract_single.py")
    print("=" * 60)


def run_real_extraction(file_path: str | None = None, model: str = "claude-haiku-4-5"):
    """Run the full pipeline with real API calls."""
    from dotenv import load_dotenv
    load_dotenv()

    from anthropic import Anthropic

    try:
        client = Anthropic()
    except Exception as e:
        print(f"Error: Could not initialize Anthropic client: {e}")
        print("Make sure ANTHROPIC_API_KEY is set in your .env file.")
        sys.exit(1)

    print("=" * 60)
    print("STRUCTURED DATA EXTRACTION PIPELINE — LIVE RUN")
    print("=" * 60)
    print()

    # Load document
    if file_path and Path(file_path).exists():
        doc = load_document(Path(file_path))
        text_content = doc.text_content
        source_file = doc.file_name
        doc_type = doc.document_type
        print(f"[LOAD] Loaded: {source_file}")
        print(f"       Type: {doc_type} | Pages: {doc.page_count}")
    else:
        text_content = SAMPLE_IPID_TEXT
        source_file = "IPID API Santé Equilibre (sample)"
        doc_type = "ipid"
        print(f"[LOAD] Using built-in sample IPID document")

    print(f"       Text length: {len(text_content):,} chars")
    print()

    # --- Check if document type is supported ---
    if not is_extraction_supported(doc_type):
        print(f"[SKIP] Document type '{doc_type}' is not supported for extraction.")
        print(f"       Reason: {get_unsupported_reason(doc_type)}")
        print()
        print("       Supported types: ipid, guarantee_table")
        print("       To add support, implement:")
        print("         1. Pydantic model in schemas.py")
        print("         2. tool_use definition in extraction.py")
        print("         3. Validation rules in validation.py")
        print()
        print("       This document was skipped — no API call was made.")
        print("       (Graceful degradation: CCA-F Domain 5 — Reliability)")
        return
    
    # Extract with retry
    token_usage = TokenUsage()
    print("[EXTRACT] Running extraction with retry loop...")
    result = extract_with_retry(
        text_content=text_content,
        document_type=doc_type,
        source_file=source_file,
        client=client,
        model=model,
        token_usage=token_usage,
        config=RetryConfig(max_retries=2),
    )

    print(f"          {result.summary()}")
    print(f"          {token_usage.summary()}")
    print()

    # Show extraction result
    if result.final_result.ipid:
        ipid = result.final_result.ipid
        print("[RESULT] IPID Extraction:")
        print(f"         Product: {ipid.product_name}")
        print(f"         Insurer: {ipid.insurer_name}")
        print(f"         Registration: {ipid.insurer_registration}")
        print(f"         Madelin eligible: {ipid.madelin_eligible}")
        print(f"         Responsible contract: {ipid.responsible_contract}")
        print(f"         Covered items: {len(ipid.covered_items)}")
        print(f"         Not covered: {len(ipid.not_covered_items)}")
        print(f"         Exclusions: {len(ipid.exclusions)}")
        if ipid.field_confidences:
            print(f"         Low-confidence fields: {ipid.field_confidences}")
    elif result.final_result.guarantee_table:
        bg = result.final_result.guarantee_table
        print("[RESULT] Guarantee Table Extraction:")
        print(f"         Product: {bg.product_name}")
        print(f"         Level: {bg.guarantee_level}")
        print(f"         Benefits: {len(bg.benefits)}")
        print(f"         Comfort pack: {bg.has_comfort_pack}")
    print()

    # Validation details
    print(f"[VALIDATION] {result.final_validation.summary()}")
    if result.final_validation.warnings:
        for w in result.final_validation.warnings:
            print(f"             ⚠ {w.field_path}: {w.message}")
    print()

    # Confidence routing
    review_decision = route_for_review(result.final_result)
    print(f"[ROUTING] {review_decision.summary()}")
    if review_decision.flagged_fields:
        for f in review_decision.flagged_fields:
            print(f"          → {f.field_name}: {f.confidence.value} — {f.reason}")
    print()

    # Save JSON output
    output_path = Path("data/results/last_extraction.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if result.final_result.ipid:
        output_data = result.final_result.ipid.model_dump(mode="json")
    elif result.final_result.guarantee_table:
        output_data = result.final_result.guarantee_table.model_dump(mode="json")
    else:
        output_data = {"error": result.final_result.extraction_errors}

    output_path.write_text(
        json.dumps(output_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[SAVE] Extraction saved to {output_path}")
    print()

    print("=" * 60)
    print(f"TOTAL COST: {token_usage.summary()}")
    print("=" * 60)


if __name__ == "__main__":
    import os

    # Parse --model if provided
    model = "claude-haiku-4-5"
    remaining_args = []
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
            i += 2
        else:
            remaining_args.append(sys.argv[i])
            i += 1
    file_arg = remaining_args[0] if remaining_args else None

    if os.getenv("ANTHROPIC_API_KEY") or (file_arg and Path(file_arg).exists()):
        # Try loading .env first
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        if os.getenv("ANTHROPIC_API_KEY"):
            run_real_extraction(file_arg, model=model)
        else:
            run_demo_dry_run()
    else:
        run_demo_dry_run()
