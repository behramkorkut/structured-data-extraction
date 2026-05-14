"""
Pydantic models and JSON schemas for insurance document extraction.

Covers two primary document types:
- IPID (Insurance Product Information Document): standardized EU format
- Guarantee Table (Barème de Garanties): coverage levels and reimbursement rates

Design decisions aligned with CCA-F Scenario 6, Task 4.3:
- Nullable fields: when source document may not contain the information,
  the model returns None instead of fabricating values.
- Enum with "other" + detail: for extensible categorization of coverage types.
- Required vs optional: only fields guaranteed to exist in the document type
  are required; everything else is optional to prevent hallucination.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared enums and base models
# ---------------------------------------------------------------------------


class DocumentType(StrEnum):
    """Type of insurance document being processed."""

    IPID = "ipid"
    GUARANTEE_TABLE = "guarantee_table"
    PRODUCT_SHEET = "product_sheet"
    PRICING = "pricing"
    REIMBURSEMENT_EXAMPLE = "reimbursement_example"
    INFORMATION_NOTICE = "information_notice"
    COMMERCIAL_BROCHURE = "commercial_brochure"
    UNKNOWN = "unknown"


class CoverageCategory(StrEnum):
    """Main categories of health insurance coverage.

    Uses "other" + detail pattern for extensible categorization
    as recommended by CCA-F Task 4.3.
    """

    ROUTINE_CARE = "routine_care"  # Soins courants
    HOSPITALIZATION = "hospitalization"  # Hospitalisation
    OPTICAL = "optical"  # Optique
    DENTAL = "dental"  # Dentaire
    HEARING = "hearing"  # Aides auditives
    PREVENTION = "prevention"  # Prévention
    COMFORT_PACK = "comfort_pack"  # Pack confort (options)
    OTHER = "other"  # Extensible — requires detail field


class ReimbursementType(StrEnum):
    """How the reimbursement is expressed in the document.

    Insurance documents use varied formats:
    - "100% BR - SS" (percentage of base rate minus social security)
    - "30 € / séance" (fixed amount per session)
    - "Zéro reste à charge" (zero out-of-pocket)
    """

    PERCENTAGE_BR_MINUS_SS = "percentage_br_minus_ss"  # e.g., "100% BR - SS"
    PERCENTAGE_BR = "percentage_br"  # e.g., "150% BR"
    FIXED_AMOUNT = "fixed_amount"  # e.g., "30 € / séance"
    REAL_COSTS = "real_costs"  # "Frais Réels" or "100% FR"
    ZERO_COPAY = "zero_copay"  # "Zéro reste à charge"
    OTHER = "other"


class FieldConfidence(StrEnum):
    """Confidence level for an extracted field.

    Used for human review routing (CCA-F Task 5.5):
    - HIGH: clearly stated in document, unambiguous
    - MEDIUM: inferred from context, partially stated
    - LOW: ambiguous, conflicting, or poorly formatted source
    - NOT_FOUND: field not present in document (returns None)
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_FOUND = "not_found"


# ---------------------------------------------------------------------------
# Field-level confidence wrapper
# ---------------------------------------------------------------------------


class ConfidenceWrapper(BaseModel):
    """Wraps an extracted value with field-level confidence.

    This enables human review routing: fields with low confidence
    are flagged for manual verification.
    """

    confidence: FieldConfidence = Field(
        description="Confidence in the extraction accuracy for this specific field."
    )
    reasoning: str | None = Field(
        default=None,
        description=(
            "Brief explanation of why confidence is not HIGH. "
            "Only populated for MEDIUM or LOW confidence."
        ),
    )


# ---------------------------------------------------------------------------
# IPID Extraction Schema
# ---------------------------------------------------------------------------


class InsuredItem(BaseModel):
    """A single item or category that is covered by the insurance."""

    description: str = Field(
        description="Description of what is covered, as stated in the document."
    )
    category: CoverageCategory = Field(description="Coverage category this item belongs to.")
    category_detail: str | None = Field(
        default=None,
        description=(
            "Detail string when category is 'other'. "
            "Explains the non-standard category. Must be populated if category='other'."
        ),
    )
    conditions: str | None = Field(
        default=None,
        description="Any conditions, limits or restrictions mentioned for this item.",
    )


class ExclusionItem(BaseModel):
    """A single exclusion or restriction on coverage."""

    description: str = Field(description="Description of what is excluded or restricted.")
    exclusion_type: str = Field(
        description=(
            "Type of exclusion: 'absolute' (never covered), "
            "'conditional' (excluded under certain conditions), "
            "or 'regulatory' (excluded by responsible contract rules)."
        ),
    )


class IPIDExtraction(BaseModel):
    """Structured extraction from an IPID (Insurance Product Information Document).

    The IPID is a standardized EU document (IDD directive) with fixed sections.
    All section fields are required because IPIDs must contain these sections
    by regulation. However, individual items within sections are nullable
    when the document is incomplete or damaged.

    CCA-F Task 4.3: required fields for sections that must exist by regulation,
    nullable sub-fields for content that may be missing.
    """

    # --- Product identification (required — always present in IPID) ---
    product_name: str = Field(description="Full product name as stated in the document header.")
    insurer_name: str = Field(description="Name of the insurance company or mutual.")
    insurer_registration: str | None = Field(
        default=None,
        description="SIRENE number or registration identifier of the insurer.",
    )
    insurance_type: str = Field(
        description=(
            "Type of insurance described in the 'De quel type d'assurance s'agit-il?' section. "
            "Extract the full description, not just a category label."
        ),
    )

    # --- Target population ---
    eligible_population: str | None = Field(
        default=None,
        description="Who can subscribe (age limits, conditions).",
    )
    madelin_eligible: bool | None = Field(
        default=None,
        description="Whether the product is eligible for Loi Madelin tax benefits.",
    )
    responsible_contract: bool | None = Field(
        default=None,
        description="Whether the product complies with 'contrat responsable' regulations.",
    )

    # --- Coverage sections ---
    covered_items: list[InsuredItem] = Field(
        description="List of items/categories that ARE covered by the insurance."
    )
    not_covered_items: list[str] = Field(
        description=(
            "List of items explicitly stated as NOT covered. "
            "From the 'Qu'est-ce qui n'est pas assuré?' section."
        ),
    )
    exclusions: list[ExclusionItem] = Field(description="Exclusions and restrictions on coverage.")

    # --- Optional/comfort guarantees ---
    optional_guarantees: list[str] | None = Field(
        default=None,
        description="Optional add-on guarantees (renforts, packs confort).",
    )

    # --- Services ---
    included_services: list[str] | None = Field(
        default=None,
        description="Services included (tiers payant, télétransmission, online portal, etc.).",
    )

    # --- Geographic coverage ---
    geographic_coverage: str | None = Field(
        default=None,
        description="Where the insurance applies (France, overseas, abroad).",
    )

    # --- Payment and contract ---
    payment_frequency: list[str] | None = Field(
        default=None,
        description="Available payment frequencies (monthly, quarterly, etc.).",
    )
    contract_duration: str | None = Field(
        default=None,
        description="Contract duration and renewal terms.",
    )
    cancellation_terms: str | None = Field(
        default=None,
        description="How and when the contract can be cancelled.",
    )

    # --- Document metadata ---
    document_reference: str | None = Field(
        default=None,
        description="Document reference code (e.g., 'SP24/FCR0103').",
    )
    last_updated: str | None = Field(
        default=None,
        description="Date of last update as stated in the document (e.g., '05/2024').",
    )

    # --- Confidence ---
    field_confidences: dict[str, FieldConfidence] | None = Field(
        default=None,
        description=(
            "Per-field confidence scores. Keys are field names from this schema, "
            "values are confidence levels. Only include fields with non-HIGH confidence."
        ),
    )


# ---------------------------------------------------------------------------
# Guarantee Table (Barème de Garanties) Extraction Schema
# ---------------------------------------------------------------------------


class ReimbursementLevel(BaseModel):
    """A single reimbursement level for a specific benefit.

    Captures the varied formats used in French insurance guarantee tables.
    """

    raw_value: str = Field(
        description=(
            "The reimbursement value exactly as written in the document. "
            "e.g., '100 % BR - SS', '30 € / séance 5 séances max', 'Zéro reste à charge'."
        ),
    )
    reimbursement_type: ReimbursementType = Field(
        description="Categorization of how the reimbursement is expressed."
    )
    reimbursement_type_detail: str | None = Field(
        default=None,
        description="Detail when reimbursement_type is 'other'.",
    )
    percentage: float | None = Field(
        default=None,
        description="Percentage value when applicable (e.g., 100.0 for '100% BR-SS').",
    )
    fixed_amount_euros: float | None = Field(
        default=None,
        description="Fixed amount in euros when applicable (e.g., 30.0 for '30 €/séance').",
    )
    unit: str | None = Field(
        default=None,
        description="Unit for the reimbursement (e.g., '/séance', '/an', '/oreille').",
    )
    frequency_limit: str | None = Field(
        default=None,
        description="Frequency limitation (e.g., '5 séances max', 'tous les 2 ans').",
    )
    annual_cap: str | None = Field(
        default=None,
        description="Annual maximum if mentioned (e.g., 'limité à 2 implants').",
    )


class GuaranteeBenefit(BaseModel):
    """A single benefit line item from a guarantee table."""

    benefit_name: str = Field(description="Name of the benefit/service as stated in the table.")
    benefit_detail: str | None = Field(
        default=None,
        description="Additional detail or sub-category for the benefit.",
    )
    category: CoverageCategory = Field(
        description="Which main coverage category this benefit belongs to."
    )
    category_detail: str | None = Field(
        default=None,
        description="Detail when category is 'other'.",
    )
    reimbursement: ReimbursementLevel = Field(description="Reimbursement level for this benefit.")
    conditions: str | None = Field(
        default=None,
        description="Special conditions, footnotes, or restrictions for this benefit.",
    )
    requires_social_security: bool | None = Field(
        default=None,
        description="Whether Social Security coverage is required for reimbursement.",
    )


class ComfortPackOption(BaseModel):
    """An option within a comfort pack (Pack Confort Jeunes/Familles/Seniors)."""

    benefit_name: str = Field(description="Name of the comfort benefit.")
    formula_levels: dict[str, str] = Field(
        description=(
            "Reimbursement per formula level. "
            "Keys are formula names (e.g., 'PC1', 'PC2', 'PC3'), "
            "values are the reimbursement as stated in the document."
        ),
    )
    conditions: str | None = Field(
        default=None,
        description="Conditions or limits for this comfort benefit.",
    )


class GuaranteeTableExtraction(BaseModel):
    """Structured extraction from a Guarantee Table (Barème de Garanties).

    Captures the full structure of a French health insurance guarantee table:
    product info, coverage level, all benefit lines with reimbursement rates,
    and optional comfort packs.

    CCA-F Task 4.3: nullable fields for benefits that may not appear in all
    guarantee levels (e.g., chirurgie réfractive only in higher levels).
    """

    # --- Product identification ---
    product_name: str = Field(
        description="Full product name (e.g., 'API Santé - Gamme Équilibre')."
    )
    guarantee_level: str = Field(
        description="Coverage level name (e.g., 'Equilibre 1', 'Sérénité 3')."
    )
    has_comfort_pack: bool = Field(
        description="Whether this document includes a comfort pack option (Pack Confort)."
    )
    comfort_pack_type: str | None = Field(
        default=None,
        description="Type of comfort pack: 'Jeunes et Familles', 'Seniors', or None.",
    )

    # --- Core benefits ---
    benefits: list[GuaranteeBenefit] = Field(
        description="All benefit line items extracted from the guarantee table."
    )

    # --- Comfort pack details (optional — not all BGs include these) ---
    comfort_pack_options: list[ComfortPackOption] | None = Field(
        default=None,
        description="Comfort pack options when present in the document.",
    )

    # --- Footnotes and conditions ---
    footnotes: list[str] | None = Field(
        default=None,
        description="Footnotes from the guarantee table that clarify conditions.",
    )
    lexicon: dict[str, str] | None = Field(
        default=None,
        description=(
            "Abbreviation definitions from the document's lexicon section. "
            "e.g., {'BR': 'Base de Remboursement', 'SS': 'Sécurité Sociale'}."
        ),
    )

    # --- Document metadata ---
    document_reference: str | None = Field(
        default=None,
        description="Document reference code.",
    )
    last_updated: str | None = Field(
        default=None,
        description="Date of last update.",
    )

    # --- Confidence ---
    field_confidences: dict[str, FieldConfidence] | None = Field(
        default=None,
        description=("Per-field confidence scores. Only include fields with non-HIGH confidence."),
    )


# ---------------------------------------------------------------------------
# Unified extraction result
# ---------------------------------------------------------------------------


class ExtractionResult(BaseModel):
    """Unified wrapper for any extraction result.

    Allows downstream processing to handle all document types uniformly
    while preserving the specific schema for each type.
    """

    document_type: DocumentType = Field(description="The type of document that was processed.")
    source_file: str = Field(description="Original filename of the source document.")
    ipid: IPIDExtraction | None = Field(
        default=None,
        description="IPID extraction result. Populated when document_type is 'ipid'.",
    )
    guarantee_table: GuaranteeTableExtraction | None = Field(
        default=None,
        description=(
            "Guarantee table extraction. Populated when document_type is 'guarantee_table'."
        ),
    )
    extraction_errors: list[str] | None = Field(
        default=None,
        description="Any errors encountered during extraction.",
    )


# ---------------------------------------------------------------------------
# JSON Schema generation for tool_use
# ---------------------------------------------------------------------------


def get_ipid_tool_schema() -> dict:
    """Generate the JSON schema for the IPID extraction tool.

    This schema is used as the input_schema for a Claude tool_use call,
    guaranteeing schema-compliant structured output.

    Returns:
        JSON schema dict compatible with Claude's tool_use input_schema.
    """
    return IPIDExtraction.model_json_schema()


def get_guarantee_table_tool_schema() -> dict:
    """Generate the JSON schema for the guarantee table extraction tool.

    Returns:
        JSON schema dict compatible with Claude's tool_use input_schema.
    """
    return GuaranteeTableExtraction.model_json_schema()
