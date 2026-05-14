"""Tests for schemas module.

Validates Pydantic models, JSON schema generation, and design decisions:
- Nullable fields return None (not fabricated values)
- Enum "other" + detail pattern works correctly
- Required vs optional field behavior
- Schema generation for tool_use
"""

import json

import pytest
from pydantic import ValidationError

from src.structured_extraction.schemas import (
    ComfortPackOption,
    CoverageCategory,
    DocumentType,
    ExclusionItem,
    ExtractionResult,
    FieldConfidence,
    GuaranteeBenefit,
    GuaranteeTableExtraction,
    InsuredItem,
    IPIDExtraction,
    ReimbursementLevel,
    ReimbursementType,
    get_guarantee_table_tool_schema,
    get_ipid_tool_schema,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnums:
    """Test enum definitions and the 'other' + detail pattern."""

    def test_coverage_category_has_other(self):
        """CCA-F Task 4.3: enum must include 'other' for extensibility."""
        assert CoverageCategory.OTHER == "other"

    def test_reimbursement_type_has_other(self):
        assert ReimbursementType.OTHER == "other"

    def test_document_type_values(self):
        assert DocumentType.IPID == "ipid"
        assert DocumentType.GUARANTEE_TABLE == "guarantee_table"
        assert DocumentType.UNKNOWN == "unknown"

    def test_field_confidence_levels(self):
        assert FieldConfidence.HIGH == "high"
        assert FieldConfidence.NOT_FOUND == "not_found"

    @pytest.mark.parametrize(
        "category",
        [
            CoverageCategory.ROUTINE_CARE,
            CoverageCategory.HOSPITALIZATION,
            CoverageCategory.OPTICAL,
            CoverageCategory.DENTAL,
            CoverageCategory.HEARING,
            CoverageCategory.PREVENTION,
            CoverageCategory.COMFORT_PACK,
            CoverageCategory.OTHER,
        ],
    )
    def test_all_coverage_categories_are_valid(self, category: CoverageCategory):
        """Ensure all expected coverage categories exist."""
        assert category in CoverageCategory


# ---------------------------------------------------------------------------
# InsuredItem tests
# ---------------------------------------------------------------------------


class TestInsuredItem:
    """Test the InsuredItem model (covered items in IPID)."""

    def test_basic_insured_item(self):
        item = InsuredItem(
            description="Consultations généralistes et spécialistes",
            category=CoverageCategory.ROUTINE_CARE,
        )
        assert item.description == "Consultations généralistes et spécialistes"
        assert item.category == CoverageCategory.ROUTINE_CARE
        assert item.category_detail is None
        assert item.conditions is None

    def test_other_category_with_detail(self):
        """CCA-F Task 4.3: 'other' + detail string pattern."""
        item = InsuredItem(
            description="Cure thermale prise en charge par la SS",
            category=CoverageCategory.OTHER,
            category_detail="Thermal cure / spa treatment",
        )
        assert item.category == CoverageCategory.OTHER
        assert item.category_detail == "Thermal cure / spa treatment"

    def test_item_with_conditions(self):
        item = InsuredItem(
            description="Chirurgie réfractive",
            category=CoverageCategory.OPTICAL,
            conditions="Selon niveau souscrit",
        )
        assert item.conditions == "Selon niveau souscrit"

    def test_nullable_fields_default_to_none(self):
        """CCA-F Task 4.3: nullable fields prevent hallucination."""
        item = InsuredItem(
            description="Test",
            category=CoverageCategory.ROUTINE_CARE,
        )
        assert item.category_detail is None
        assert item.conditions is None


# ---------------------------------------------------------------------------
# ReimbursementLevel tests
# ---------------------------------------------------------------------------


class TestReimbursementLevel:
    """Test reimbursement level extraction with varied formats."""

    def test_percentage_br_minus_ss(self):
        level = ReimbursementLevel(
            raw_value="100 % BR - SS",
            reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
            percentage=100.0,
        )
        assert level.raw_value == "100 % BR - SS"
        assert level.percentage == 100.0
        assert level.fixed_amount_euros is None

    def test_fixed_amount_per_session(self):
        level = ReimbursementLevel(
            raw_value="30 € / séance 5 séances max",
            reimbursement_type=ReimbursementType.FIXED_AMOUNT,
            fixed_amount_euros=30.0,
            unit="/séance",
            frequency_limit="5 séances max",
        )
        assert level.fixed_amount_euros == 30.0
        assert level.unit == "/séance"
        assert level.frequency_limit == "5 séances max"

    def test_zero_copay(self):
        level = ReimbursementLevel(
            raw_value="Zéro reste à charge dans la limite du panier 100% Santé",
            reimbursement_type=ReimbursementType.ZERO_COPAY,
        )
        assert level.reimbursement_type == ReimbursementType.ZERO_COPAY
        assert level.percentage is None
        assert level.fixed_amount_euros is None

    def test_real_costs(self):
        level = ReimbursementLevel(
            raw_value="100 % FR",
            reimbursement_type=ReimbursementType.REAL_COSTS,
            percentage=100.0,
        )
        assert level.reimbursement_type == ReimbursementType.REAL_COSTS

    def test_nullable_fields_all_none(self):
        """All optional fields should default to None."""
        level = ReimbursementLevel(
            raw_value="Non précisé",
            reimbursement_type=ReimbursementType.OTHER,
            reimbursement_type_detail="Format not recognized",
        )
        assert level.percentage is None
        assert level.fixed_amount_euros is None
        assert level.unit is None
        assert level.frequency_limit is None
        assert level.annual_cap is None


# ---------------------------------------------------------------------------
# GuaranteeBenefit tests
# ---------------------------------------------------------------------------


class TestGuaranteeBenefit:
    """Test guarantee benefit line items."""

    def test_basic_benefit(self):
        benefit = GuaranteeBenefit(
            benefit_name="Analyses et examens de biologie médicale",
            category=CoverageCategory.ROUTINE_CARE,
            reimbursement=ReimbursementLevel(
                raw_value="100 % BR - SS",
                reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                percentage=100.0,
            ),
        )
        assert benefit.benefit_name == "Analyses et examens de biologie médicale"
        assert benefit.reimbursement.percentage == 100.0

    def test_benefit_with_social_security_requirement(self):
        benefit = GuaranteeBenefit(
            benefit_name="Lentilles prises en charge par la SS",
            category=CoverageCategory.OPTICAL,
            reimbursement=ReimbursementLevel(
                raw_value="100 % BR - SS",
                reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                percentage=100.0,
            ),
            requires_social_security=True,
        )
        assert benefit.requires_social_security is True

    def test_benefit_nullable_fields(self):
        benefit = GuaranteeBenefit(
            benefit_name="Test",
            category=CoverageCategory.DENTAL,
            reimbursement=ReimbursementLevel(
                raw_value="100 % BR - SS",
                reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
            ),
        )
        assert benefit.benefit_detail is None
        assert benefit.conditions is None
        assert benefit.requires_social_security is None


# ---------------------------------------------------------------------------
# ComfortPackOption tests
# ---------------------------------------------------------------------------


class TestComfortPackOption:
    """Test comfort pack option extraction."""

    def test_comfort_pack_with_formula_levels(self):
        option = ComfortPackOption(
            benefit_name="Ostéopathe, acupuncteur, pédicure-podologue",
            formula_levels={
                "PC1": "30 € / séance 5 séances max",
                "PC2": "40 € / séance 5 séances max",
                "PC3": "50 € / séance 5 séances max",
            },
            conditions="Séances non prises en charge par la Sécurité sociale",
        )
        assert len(option.formula_levels) == 3
        assert "PC1" in option.formula_levels
        assert option.formula_levels["PC2"] == "40 € / séance 5 séances max"


# ---------------------------------------------------------------------------
# IPIDExtraction tests
# ---------------------------------------------------------------------------


class TestIPIDExtraction:
    """Test the full IPID extraction model."""

    @pytest.fixture
    def minimal_ipid(self) -> IPIDExtraction:
        """Minimal valid IPID with only required fields."""
        return IPIDExtraction(
            product_name="API Santé Équilibre",
            insurer_name="APICIL Mutuelle",
            insurance_type="Assurance complémentaire santé",
            covered_items=[
                InsuredItem(
                    description="Soins courants",
                    category=CoverageCategory.ROUTINE_CARE,
                )
            ],
            not_covered_items=["Chirurgie esthétique non prise en charge par la SS"],
            exclusions=[
                ExclusionItem(
                    description="Participation forfaitaire consultations",
                    exclusion_type="regulatory",
                )
            ],
        )

    def test_minimal_ipid_valid(self, minimal_ipid: IPIDExtraction):
        assert minimal_ipid.product_name == "API Santé Équilibre"
        assert len(minimal_ipid.covered_items) == 1
        assert len(minimal_ipid.not_covered_items) == 1

    def test_nullable_fields_default_to_none(self, minimal_ipid: IPIDExtraction):
        """CCA-F Task 4.3: optional fields are None, not fabricated."""
        assert minimal_ipid.insurer_registration is None
        assert minimal_ipid.eligible_population is None
        assert minimal_ipid.madelin_eligible is None
        assert minimal_ipid.geographic_coverage is None
        assert minimal_ipid.payment_frequency is None
        assert minimal_ipid.document_reference is None
        assert minimal_ipid.last_updated is None
        assert minimal_ipid.field_confidences is None

    def test_required_fields_missing_raises_error(self):
        """Required fields must be provided — model should not accept missing ones."""
        with pytest.raises(ValidationError):
            IPIDExtraction(
                # Missing product_name, insurer_name, insurance_type
                covered_items=[],
                not_covered_items=[],
                exclusions=[],
            )

    def test_full_ipid_with_all_fields(self):
        """Test a fully populated IPID extraction."""
        ipid = IPIDExtraction(
            product_name="API Santé Équilibre",
            insurer_name="APICIL Mutuelle",
            insurer_registration="302 927 553",
            insurance_type=(
                "Assurance complémentaire santé destinée à rembourser les frais de santé"
            ),
            eligible_population="Personnes physiques âgées de 16 ans minimum",
            madelin_eligible=True,
            responsible_contract=True,
            covered_items=[
                InsuredItem(
                    description="Consultations généralistes et spécialistes",
                    category=CoverageCategory.ROUTINE_CARE,
                ),
                InsuredItem(
                    description="Forfait journalier hospitalier",
                    category=CoverageCategory.HOSPITALIZATION,
                ),
            ],
            not_covered_items=[
                "Soins hors période de validité",
                "Chirurgie esthétique non prise en charge par la SS",
            ],
            exclusions=[
                ExclusionItem(
                    description="Participation forfaitaire consultations médicales",
                    exclusion_type="regulatory",
                ),
                ExclusionItem(
                    description="Majoration ticket modérateur hors parcours de soins",
                    exclusion_type="regulatory",
                ),
            ],
            optional_guarantees=[
                "Renfort HOSPI+",
                "Renfort FAMILLE",
                "Pack Confort Jeunes/Familles",
                "Pack Confort Seniors",
            ],
            included_services=["Tiers payant", "Télétransmission", "Espace en ligne"],
            geographic_coverage=(
                "France métropolitaine, DROM, étranger sur base tarif convention SS"
            ),
            payment_frequency=["mensuel", "trimestriel", "semestriel", "annuel"],
            contract_duration="1 an, renouvellement automatique",
            cancellation_terms=(
                "Résiliation au 31/12 avec préavis 2 mois, ou à tout moment après 1 an"
            ),
            document_reference="SP24/FCR0103",
            last_updated="05/2024",
            field_confidences={
                "insurer_registration": FieldConfidence.MEDIUM,
            },
        )
        assert ipid.madelin_eligible is True
        assert len(ipid.covered_items) == 2
        assert len(ipid.optional_guarantees) == 4
        assert ipid.field_confidences["insurer_registration"] == FieldConfidence.MEDIUM


# ---------------------------------------------------------------------------
# GuaranteeTableExtraction tests
# ---------------------------------------------------------------------------


class TestGuaranteeTableExtraction:
    """Test the full guarantee table extraction model."""

    @pytest.fixture
    def minimal_bg(self) -> GuaranteeTableExtraction:
        """Minimal valid guarantee table."""
        return GuaranteeTableExtraction(
            product_name="API Santé - Gamme Équilibre",
            guarantee_level="Equilibre 1",
            has_comfort_pack=False,
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Analyses et examens de biologie médicale",
                    category=CoverageCategory.ROUTINE_CARE,
                    reimbursement=ReimbursementLevel(
                        raw_value="100 % BR - SS",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                        percentage=100.0,
                    ),
                ),
            ],
        )

    def test_minimal_bg_valid(self, minimal_bg: GuaranteeTableExtraction):
        assert minimal_bg.guarantee_level == "Equilibre 1"
        assert len(minimal_bg.benefits) == 1

    def test_nullable_fields(self, minimal_bg: GuaranteeTableExtraction):
        assert minimal_bg.comfort_pack_type is None
        assert minimal_bg.comfort_pack_options is None
        assert minimal_bg.footnotes is None
        assert minimal_bg.lexicon is None

    def test_bg_with_comfort_pack(self):
        bg = GuaranteeTableExtraction(
            product_name="API Santé - Gamme Équilibre",
            guarantee_level="Equilibre 1",
            has_comfort_pack=True,
            comfort_pack_type="Jeunes et Familles",
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Analyses",
                    category=CoverageCategory.ROUTINE_CARE,
                    reimbursement=ReimbursementLevel(
                        raw_value="100 % BR - SS",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                    ),
                ),
            ],
            comfort_pack_options=[
                ComfortPackOption(
                    benefit_name="Ostéopathe",
                    formula_levels={
                        "PC1": "30 €/séance",
                        "PC2": "40 €/séance",
                        "PC3": "50 €/séance",
                    },
                ),
            ],
            lexicon={
                "BR": "Base de Remboursement",
                "SS": "Sécurité Sociale",
                "FR": "Frais Réels",
            },
        )
        assert bg.has_comfort_pack is True
        assert len(bg.comfort_pack_options) == 1
        assert bg.lexicon["BR"] == "Base de Remboursement"


# ---------------------------------------------------------------------------
# ExtractionResult tests
# ---------------------------------------------------------------------------


class TestExtractionResult:
    """Test the unified extraction result wrapper."""

    def test_ipid_result(self):
        result = ExtractionResult(
            document_type=DocumentType.IPID,
            source_file="IPID API Santé Equilibre.pdf",
            ipid=IPIDExtraction(
                product_name="API Santé Équilibre",
                insurer_name="APICIL Mutuelle",
                insurance_type="Complémentaire santé",
                covered_items=[],
                not_covered_items=[],
                exclusions=[],
            ),
        )
        assert result.document_type == DocumentType.IPID
        assert result.ipid is not None
        assert result.guarantee_table is None

    def test_guarantee_table_result(self):
        result = ExtractionResult(
            document_type=DocumentType.GUARANTEE_TABLE,
            source_file="BG Equilibre 1.pdf",
            guarantee_table=GuaranteeTableExtraction(
                product_name="API Santé",
                guarantee_level="Equilibre 1",
                has_comfort_pack=False,
                benefits=[],
            ),
        )
        assert result.document_type == DocumentType.GUARANTEE_TABLE
        assert result.guarantee_table is not None
        assert result.ipid is None

    def test_result_with_errors(self):
        result = ExtractionResult(
            document_type=DocumentType.UNKNOWN,
            source_file="corrupted.pdf",
            extraction_errors=["Failed to extract text from PDF"],
        )
        assert len(result.extraction_errors) == 1


# ---------------------------------------------------------------------------
# JSON Schema generation tests
# ---------------------------------------------------------------------------


class TestSchemaGeneration:
    """Test JSON schema generation for Claude tool_use."""

    def test_ipid_schema_is_valid_json_schema(self):
        schema = get_ipid_tool_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "product_name" in schema["properties"]
        assert "covered_items" in schema["properties"]

    def test_guarantee_table_schema_is_valid_json_schema(self):
        schema = get_guarantee_table_tool_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "benefits" in schema["properties"]
        assert "guarantee_level" in schema["properties"]

    def test_ipid_schema_serializable(self):
        """Schema must be JSON-serializable for the Claude API."""
        schema = get_ipid_tool_schema()
        json_str = json.dumps(schema)
        assert len(json_str) > 0

    def test_guarantee_table_schema_serializable(self):
        schema = get_guarantee_table_tool_schema()
        json_str = json.dumps(schema)
        assert len(json_str) > 0

    def test_ipid_schema_has_descriptions(self):
        """Tool schemas should include field descriptions for Claude."""
        schema = get_ipid_tool_schema()
        props = schema["properties"]
        for field_name, field_schema in props.items():
            # Every field should have a description for Claude to understand
            assert (
                "description" in field_schema or "$ref" in field_schema or "allOf" in field_schema
            ), f"Field '{field_name}' missing description in schema"
