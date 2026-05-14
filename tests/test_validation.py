"""Tests for the semantic validation layer.

CCA-F Task 4.4: validates what JSON schemas cannot —
internal consistency, value plausibility, completeness.
"""

from src.structured_extraction.schemas import (
    CoverageCategory,
    DocumentType,
    ExclusionItem,
    ExtractionResult,
    GuaranteeBenefit,
    GuaranteeTableExtraction,
    InsuredItem,
    IPIDExtraction,
    ReimbursementLevel,
    ReimbursementType,
)
from src.structured_extraction.validation import (
    ValidationError,
    ValidationErrorCategory,
    ValidationResult,
    ValidationSeverity,
    validate_extraction,
    validate_guarantee_table,
    validate_ipid,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_ipid(**overrides) -> IPIDExtraction:
    """Create a minimal valid IPID for testing."""
    defaults = {
        "product_name": "API Santé Équilibre",
        "insurer_name": "APICIL Mutuelle",
        "insurance_type": "Assurance complémentaire santé",
        "responsible_contract": True,
        "covered_items": [
            InsuredItem(description="Soins courants", category=CoverageCategory.ROUTINE_CARE),
            InsuredItem(description="Hospitalisation", category=CoverageCategory.HOSPITALIZATION),
            InsuredItem(description="Optique", category=CoverageCategory.OPTICAL),
            InsuredItem(description="Dentaire", category=CoverageCategory.DENTAL),
        ],
        "not_covered_items": ["Chirurgie esthétique"],
        "exclusions": [
            ExclusionItem(description="Participation forfaitaire", exclusion_type="regulatory"),
        ],
    }
    defaults.update(overrides)
    return IPIDExtraction(**defaults)


def _make_valid_benefit(name: str = "Test", **overrides) -> GuaranteeBenefit:
    """Create a valid benefit for testing."""
    defaults = {
        "benefit_name": name,
        "category": CoverageCategory.ROUTINE_CARE,
        "reimbursement": ReimbursementLevel(
            raw_value="100 % BR - SS",
            reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
            percentage=100.0,
        ),
    }
    defaults.update(overrides)
    return GuaranteeBenefit(**defaults)


def _make_valid_bg(**overrides) -> GuaranteeTableExtraction:
    """Create a minimal valid guarantee table for testing."""
    defaults = {
        "product_name": "API Santé - Gamme Équilibre",
        "guarantee_level": "Equilibre 1",
        "has_comfort_pack": False,
        "benefits": [
            _make_valid_benefit("Analyses", category=CoverageCategory.ROUTINE_CARE),
            _make_valid_benefit("Forfait journalier", category=CoverageCategory.HOSPITALIZATION),
        ],
    }
    defaults.update(overrides)
    return GuaranteeTableExtraction(**defaults)


# ---------------------------------------------------------------------------
# IPID validation tests
# ---------------------------------------------------------------------------


class TestValidateIPID:
    """Test IPID semantic validation rules."""

    def test_valid_ipid_passes(self):
        result = validate_ipid(_make_valid_ipid())
        assert result.is_valid is True
        assert result.error_count == 0

    def test_empty_covered_items_is_error(self):
        """Rule 1: IPID must have covered items."""
        ipid = _make_valid_ipid(covered_items=[])
        result = validate_ipid(ipid)
        assert result.is_valid is False
        assert any(e.field_path == "covered_items" for e in result.errors)
        assert any(e.category == ValidationErrorCategory.COMPLETENESS for e in result.errors)

    def test_empty_exclusions_is_warning(self):
        """Rule 2: responsible contracts should have exclusions."""
        ipid = _make_valid_ipid(exclusions=[])
        result = validate_ipid(ipid)
        # Warning, not error
        assert any(e.field_path == "exclusions" for e in result.warnings)

    def test_responsible_contract_needs_regulatory_exclusions(self):
        """Rule 4: responsible_contract=True requires regulatory exclusions."""
        ipid = _make_valid_ipid(
            responsible_contract=True,
            exclusions=[
                ExclusionItem(description="Some exclusion", exclusion_type="absolute"),
            ],
        )
        result = validate_ipid(ipid)
        assert result.is_valid is False
        assert any(
            e.category == ValidationErrorCategory.INTERNAL_CONSISTENCY for e in result.errors
        )

    def test_missing_coverage_categories_is_warning(self):
        """Rule 5: health IPID should cover routine, hospital, optical, dental."""
        ipid = _make_valid_ipid(
            covered_items=[
                InsuredItem(description="Soins", category=CoverageCategory.ROUTINE_CARE),
                # Missing hospitalization, optical, dental
            ],
        )
        result = validate_ipid(ipid)
        assert any("Missing expected coverage categories" in e.message for e in result.warnings)

    def test_other_category_without_detail_is_error(self):
        """Rule 6: 'other' enum requires category_detail."""
        ipid = _make_valid_ipid(
            covered_items=[
                InsuredItem(description="Soins", category=CoverageCategory.ROUTINE_CARE),
                InsuredItem(
                    description="Hospitalisation", category=CoverageCategory.HOSPITALIZATION
                ),
                InsuredItem(description="Optique", category=CoverageCategory.OPTICAL),
                InsuredItem(description="Dentaire", category=CoverageCategory.DENTAL),
                InsuredItem(
                    description="Cure thermale",
                    category=CoverageCategory.OTHER,
                    category_detail=None,  # Missing!
                ),
            ],
        )
        result = validate_ipid(ipid)
        assert result.is_valid is False
        assert any("category_detail" in e.field_path for e in result.errors)

    def test_other_category_with_detail_passes(self):
        """'other' with detail should be valid."""
        ipid = _make_valid_ipid(
            covered_items=[
                InsuredItem(description="Soins", category=CoverageCategory.ROUTINE_CARE),
                InsuredItem(
                    description="Hospitalisation", category=CoverageCategory.HOSPITALIZATION
                ),
                InsuredItem(description="Optique", category=CoverageCategory.OPTICAL),
                InsuredItem(description="Dentaire", category=CoverageCategory.DENTAL),
                InsuredItem(
                    description="Cure thermale",
                    category=CoverageCategory.OTHER,
                    category_detail="Thermal cure covered by Social Security",
                ),
            ],
        )
        result = validate_ipid(ipid)
        assert result.is_valid is True

    def test_madelin_plausibility_warning(self):
        """Rule 3: Madelin eligibility should match insurance type."""
        ipid = _make_valid_ipid(
            madelin_eligible=True,
            insurance_type="Assurance auto",  # Not health/provident
        )
        result = validate_ipid(ipid)
        assert any(e.field_path == "madelin_eligible" for e in result.warnings)


# ---------------------------------------------------------------------------
# Guarantee Table validation tests
# ---------------------------------------------------------------------------


class TestValidateGuaranteeTable:
    """Test guarantee table semantic validation rules."""

    def test_valid_bg_passes(self):
        result = validate_guarantee_table(_make_valid_bg())
        assert result.is_valid is True
        assert result.error_count == 0

    def test_empty_benefits_is_error(self):
        """Rule 1: guarantee table must have benefits."""
        bg = _make_valid_bg(benefits=[])
        result = validate_guarantee_table(bg)
        assert result.is_valid is False
        assert any(e.category == ValidationErrorCategory.COMPLETENESS for e in result.errors)

    def test_comfort_pack_true_without_options_is_error(self):
        """Rule 2: has_comfort_pack=True requires comfort_pack_options."""
        bg = _make_valid_bg(
            has_comfort_pack=True,
            comfort_pack_options=None,
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False
        assert any(
            e.category == ValidationErrorCategory.INTERNAL_CONSISTENCY for e in result.errors
        )

    def test_comfort_pack_false_with_options_is_error(self):
        """Rule 2 reverse: options without flag."""
        from src.structured_extraction.schemas import ComfortPackOption

        bg = _make_valid_bg(
            has_comfort_pack=False,
            comfort_pack_options=[
                ComfortPackOption(
                    benefit_name="Ostéopathe",
                    formula_levels={"PC1": "30€"},
                ),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False

    def test_implausible_percentage_is_error(self):
        """Rule 3: percentage must be 0-600%."""
        bg = _make_valid_bg(
            benefits=[
                _make_valid_benefit(
                    "Bad benefit",
                    reimbursement=ReimbursementLevel(
                        raw_value="700 % BR - SS",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                        percentage=700.0,
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False
        assert any(e.category == ValidationErrorCategory.VALUE_PLAUSIBILITY for e in result.errors)

    def test_negative_amount_is_error(self):
        """Rule 4: fixed amounts must be non-negative."""
        bg = _make_valid_bg(
            benefits=[
                _make_valid_benefit(
                    "Bad amount",
                    reimbursement=ReimbursementLevel(
                        raw_value="-50 €",
                        reimbursement_type=ReimbursementType.FIXED_AMOUNT,
                        fixed_amount_euros=-50.0,
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False

    def test_percentage_type_without_percentage_value_is_error(self):
        """Rule 5: percentage_br_minus_ss type needs percentage value."""
        bg = _make_valid_bg(
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Bad",
                    category=CoverageCategory.ROUTINE_CARE,
                    reimbursement=ReimbursementLevel(
                        raw_value="100 % BR - SS",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                        percentage=None,  # Missing!
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False
        assert any(
            e.category == ValidationErrorCategory.INTERNAL_CONSISTENCY for e in result.errors
        )

    def test_fixed_amount_type_without_amount_is_error(self):
        """Rule 5: fixed_amount type needs fixed_amount_euros value."""
        bg = _make_valid_bg(
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Bad",
                    category=CoverageCategory.DENTAL,
                    reimbursement=ReimbursementLevel(
                        raw_value="30 €/séance",
                        reimbursement_type=ReimbursementType.FIXED_AMOUNT,
                        fixed_amount_euros=None,  # Missing!
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False

    def test_other_category_without_detail_is_error(self):
        """Rule 6: 'other' category needs detail."""
        bg = _make_valid_bg(
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Cure thermale",
                    category=CoverageCategory.OTHER,
                    category_detail=None,
                    reimbursement=ReimbursementLevel(
                        raw_value="100% BR-SS",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR_MINUS_SS,
                        percentage=100.0,
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False

    def test_other_reimbursement_type_without_detail_is_error(self):
        """Rule 7: 'other' reimbursement type needs detail."""
        bg = _make_valid_bg(
            benefits=[
                GuaranteeBenefit(
                    benefit_name="Weird benefit",
                    category=CoverageCategory.ROUTINE_CARE,
                    reimbursement=ReimbursementLevel(
                        raw_value="Selon conditions",
                        reimbursement_type=ReimbursementType.OTHER,
                        reimbursement_type_detail=None,
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert result.is_valid is False

    def test_single_category_is_warning(self):
        """Rule 8: BG should span multiple categories."""
        bg = _make_valid_bg(
            benefits=[
                _make_valid_benefit("A"),
                _make_valid_benefit("B"),
            ],
        )
        result = validate_guarantee_table(bg)
        assert any("category" in e.message.lower() for e in result.warnings)

    def test_valid_percentage_range_passes(self):
        """Plausible percentages (0-500%) should pass."""
        bg = _make_valid_bg(
            benefits=[
                _make_valid_benefit(
                    "High coverage",
                    reimbursement=ReimbursementLevel(
                        raw_value="300 % BR",
                        reimbursement_type=ReimbursementType.PERCENTAGE_BR,
                        percentage=300.0,
                    ),
                ),
                _make_valid_benefit("Other", category=CoverageCategory.HOSPITALIZATION),
            ],
        )
        result = validate_guarantee_table(bg)
        assert not any(
            e.category == ValidationErrorCategory.VALUE_PLAUSIBILITY for e in result.errors
        )


# ---------------------------------------------------------------------------
# Unified validation tests
# ---------------------------------------------------------------------------


class TestValidateExtraction:
    """Test the unified validate_extraction entry point."""

    def test_validate_ipid_extraction(self):
        result = ExtractionResult(
            document_type=DocumentType.IPID,
            source_file="test.pdf",
            ipid=_make_valid_ipid(),
        )
        validation = validate_extraction(result)
        assert validation.is_valid is True

    def test_validate_bg_extraction(self):
        result = ExtractionResult(
            document_type=DocumentType.GUARANTEE_TABLE,
            source_file="test.pdf",
            guarantee_table=_make_valid_bg(),
        )
        validation = validate_extraction(result)
        assert validation.is_valid is True

    def test_validate_extraction_with_errors(self):
        result = ExtractionResult(
            document_type=DocumentType.UNKNOWN,
            source_file="test.pdf",
            extraction_errors=["API failed"],
        )
        validation = validate_extraction(result)
        assert validation.is_valid is False

    def test_validate_empty_extraction(self):
        result = ExtractionResult(
            document_type=DocumentType.IPID,
            source_file="test.pdf",
        )
        validation = validate_extraction(result)
        assert validation.is_valid is False


# ---------------------------------------------------------------------------
# ValidationResult behavior tests
# ---------------------------------------------------------------------------


class TestValidationResult:
    """Test ValidationResult methods."""

    def test_has_retryable_errors_true(self):
        """Consistency errors are retryable."""
        result = ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="test",
                    message="Consistency error",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                ),
            ],
        )
        assert result.has_retryable_errors is True

    def test_has_retryable_errors_false_when_only_missing_content(self):
        """CCA-F Task 4.4: missing content errors are NOT retryable."""
        result = ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="test",
                    message="Info not in document",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.MISSING_CONTENT,
                ),
            ],
        )
        assert result.has_retryable_errors is False

    def test_feedback_for_retry_format(self):
        result = ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="benefits[0].percentage",
                    message="Percentage is null",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion="Extract the percentage from raw_value.",
                ),
            ],
        )
        feedback = result.get_feedback_for_retry()
        assert "benefits[0].percentage" in feedback
        assert "Percentage is null" in feedback
        assert "Suggestion:" in feedback
        assert "re-extract" in feedback.lower()

    def test_feedback_empty_when_no_errors(self):
        result = ValidationResult(is_valid=True)
        assert result.get_feedback_for_retry() == ""

    def test_summary_format(self):
        result = ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="x",
                    message="y",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.COMPLETENESS,
                )
            ],
            warnings=[
                ValidationError(
                    field_path="a",
                    message="b",
                    severity=ValidationSeverity.WARNING,
                    category=ValidationErrorCategory.VALUE_PLAUSIBILITY,
                )
            ],
        )
        summary = result.summary()
        assert "INVALID" in summary
        assert "Errors: 1" in summary
        assert "Warnings: 1" in summary
