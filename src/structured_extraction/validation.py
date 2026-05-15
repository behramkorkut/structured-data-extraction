"""
Semantic validation layer for extraction results.

CCA-F Scenario 6, Task 4.4:
- Schema syntax errors are eliminated by tool_use (guaranteed valid JSON)
- Semantic errors require explicit validation rules
- Each validation returns structured errors for retry-with-feedback

This layer catches errors that JSON schemas cannot:
- Internal consistency (comfort_pack flag vs comfort_pack_options presence)
- Category coherence (benefit category matches its content)
- Completeness (required sections not empty when document clearly contains them)
- Value plausibility (percentages within expected ranges)
"""

from dataclasses import dataclass, field
from enum import StrEnum

from src.structured_extraction.schemas import (
    CoverageCategory,
    ExtractionResult,
    GuaranteeTableExtraction,
    IPIDExtraction,
    ReimbursementType,
)

# ---------------------------------------------------------------------------
# Validation error model
# ---------------------------------------------------------------------------


class ValidationSeverity(StrEnum):
    """Severity of a validation error.

    ERROR: extraction is likely wrong, should trigger retry
    WARNING: extraction may be incomplete, flag for review
    INFO: minor inconsistency, acceptable
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationErrorCategory(StrEnum):
    """Category of validation error for structured feedback.

    CCA-F Task 4.4: structured error categories enable
    the retry loop to provide specific feedback to Claude.
    """

    INTERNAL_CONSISTENCY = "internal_consistency"
    CATEGORY_MISMATCH = "category_mismatch"
    MISSING_CONTENT = "missing_content"
    VALUE_PLAUSIBILITY = "value_plausibility"
    COMPLETENESS = "completeness"


@dataclass
class ValidationError:
    """A single validation error with structured context.

    The retry loop uses field_path and message to construct
    targeted feedback for Claude (Task 4.4).
    """

    field_path: str
    message: str
    severity: ValidationSeverity
    category: ValidationErrorCategory
    suggestion: str | None = None

    def to_feedback_string(self) -> str:
        """Format this error as feedback for the retry prompt.

        This string is appended to the retry prompt so Claude
        can understand exactly what went wrong and where.
        """
        feedback = f"- [{self.severity.value.upper()}] {self.field_path}: {self.message}"
        if self.suggestion:
            feedback += f" Suggestion: {self.suggestion}"
        return feedback


@dataclass
class ValidationResult:
    """Result of validating an extraction."""

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    infos: list[ValidationError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def has_retryable_errors(self) -> bool:
        """Whether errors are likely fixable by retry with feedback.

        CCA-F Task 4.4: retries are effective for format/structural errors,
        NOT for information absent from the source document.
        """
        return any(e.category != ValidationErrorCategory.MISSING_CONTENT for e in self.errors)

    def get_feedback_for_retry(self) -> str:
        """Generate structured feedback string for retry prompt.

        Only includes errors (not warnings/infos) to focus Claude's attention.
        """
        if not self.errors:
            return ""

        lines = ["The following validation errors were found in your extraction:"]
        for error in self.errors:
            lines.append(error.to_feedback_string())
        lines.append("\nPlease re-extract the document, correcting these specific issues.")
        return "\n".join(lines)

    def summary(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"Validation: {status} | "
            f"Errors: {self.error_count} | "
            f"Warnings: {self.warning_count} | "
            f"Infos: {len(self.infos)}"
        )


# ---------------------------------------------------------------------------
# IPID validation rules
# ---------------------------------------------------------------------------


def validate_ipid(ipid: IPIDExtraction) -> ValidationResult:
    """Validate an IPID extraction for semantic correctness.

    Args:
        ipid: The extracted IPID data.

    Returns:
        ValidationResult with categorized errors.
    """
    all_errors: list[ValidationError] = []

    # Rule 1: covered_items should not be empty (IPIDs always have coverage)
    if not ipid.covered_items:
        all_errors.append(
            ValidationError(
                field_path="covered_items",
                message="IPID has no covered items. IPIDs must describe what is covered.",
                severity=ValidationSeverity.ERROR,
                category=ValidationErrorCategory.COMPLETENESS,
                suggestion=(
                    "Re-read the 'Qu'est-ce qui est assuré?' section and extract all covered items."
                ),
            )
        )

    # Rule 2: exclusions should not be empty (responsible contracts always have exclusions)
    if not ipid.exclusions:
        all_errors.append(
            ValidationError(
                field_path="exclusions",
                message=(
                    "No exclusions found. Responsible contracts always have regulatory exclusions."
                ),
                severity=ValidationSeverity.WARNING,
                category=ValidationErrorCategory.COMPLETENESS,
                suggestion=(
                    "Check the 'Y-a-t-il des exclusions?' section for regulatory exclusions."
                ),
            )
        )

    # Rule 3: if madelin_eligible is True, product should be health or provident insurance
    if ipid.madelin_eligible is True:
        insurance_lower = ipid.insurance_type.lower()
        if "santé" not in insurance_lower and "prévoyance" not in insurance_lower:
            all_errors.append(
                ValidationError(
                    field_path="madelin_eligible",
                    message=(
                        f"Madelin eligibility is True but insurance_type '{ipid.insurance_type}' "
                        "does not appear to be health or provident insurance."
                    ),
                    severity=ValidationSeverity.WARNING,
                    category=ValidationErrorCategory.VALUE_PLAUSIBILITY,
                )
            )

    # Rule 4: if responsible_contract is True, there should be regulatory exclusions
    if ipid.responsible_contract is True:
        has_regulatory = any(e.exclusion_type == "regulatory" for e in ipid.exclusions)
        if not has_regulatory:
            all_errors.append(
                ValidationError(
                    field_path="exclusions",
                    message=(
                        "responsible_contract is True but no 'regulatory' exclusions found. "
                        "Responsible contracts must have participation forfaitaire "
                        "and franchise exclusions."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion=(
                        "Add regulatory exclusions: participation forfaitaire, "
                        "franchise médicaments, majoration ticket modérateur."
                    ),
                )
            )

    # Rule 5: coverage categories should be diverse for a health insurance IPID
    if ipid.covered_items:
        categories = {item.category for item in ipid.covered_items}
        # Only check health-specific categories for health products
        # Prévoyance (TANDEM), Accident, and Protection Décès products
        # legitimately lack dental, optical, routine_care categories
        product_name_lower = (ipid.product_name or "").lower()
        is_health_product = not any(
            keyword in product_name_lower
            for keyword in [
                "tandem",
                "accident",
                "décès",
                "deces",
                "hospitalisation",
                "prévoyance",
                "prevoyance",
            ]
        )

        if is_health_product:
            expected_categories = {
                CoverageCategory.ROUTINE_CARE,
                CoverageCategory.HOSPITALIZATION,
                CoverageCategory.OPTICAL,
                CoverageCategory.DENTAL,
            }
            missing = expected_categories - categories
            if missing:
                all_errors.append(
                    ValidationError(
                        field_path="covered_items",
                        message=(
                            f"Missing expected coverage categories: {[c.value for c in missing]}. "
                            "A standard health IPID typically covers routine care, "
                            "hospitalization, "
                            "optical, and dental."
                        ),
                        severity=ValidationSeverity.WARNING,
                        category=ValidationErrorCategory.COMPLETENESS,
                    )
                )

    # Rule 6: "other" category must have category_detail
    for i, item in enumerate(ipid.covered_items):
        if item.category == CoverageCategory.OTHER and not item.category_detail:
            all_errors.append(
                ValidationError(
                    field_path=f"covered_items[{i}].category_detail",
                    message=(
                        f"Item '{item.description}' has category='other' but no category_detail. "
                        "The 'other' category requires a detail string explaining the category."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion=(
                        "Provide a category_detail describing what type of coverage this is."
                    ),
                )
            )

    # Separate by severity
    errors = [e for e in all_errors if e.severity == ValidationSeverity.ERROR]
    warnings = [e for e in all_errors if e.severity == ValidationSeverity.WARNING]
    infos = [e for e in all_errors if e.severity == ValidationSeverity.INFO]

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        infos=infos,
    )


# ---------------------------------------------------------------------------
# Guarantee Table validation rules
# ---------------------------------------------------------------------------


def validate_guarantee_table(bg: GuaranteeTableExtraction) -> ValidationResult:
    """Validate a guarantee table extraction for semantic correctness.

    Args:
        bg: The extracted guarantee table data.

    Returns:
        ValidationResult with categorized errors.
    """
    all_errors: list[ValidationError] = []

    # Rule 1: benefits should not be empty
    if not bg.benefits:
        all_errors.append(
            ValidationError(
                field_path="benefits",
                message="Guarantee table has no benefits. Tables always contain benefit lines.",
                severity=ValidationSeverity.ERROR,
                category=ValidationErrorCategory.COMPLETENESS,
                suggestion="Extract all benefit lines from the table rows.",
            )
        )

    # Rule 2: comfort pack consistency
    if bg.has_comfort_pack and not bg.comfort_pack_options:
        all_errors.append(
            ValidationError(
                field_path="comfort_pack_options",
                message=(
                    "has_comfort_pack is True but comfort_pack_options is empty/null. "
                    "If a comfort pack is present, its options must be extracted."
                ),
                severity=ValidationSeverity.ERROR,
                category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                suggestion="Extract the Pack Confort options from the document.",
            )
        )

    if not bg.has_comfort_pack and bg.comfort_pack_options:
        all_errors.append(
            ValidationError(
                field_path="has_comfort_pack",
                message=(
                    "has_comfort_pack is False but comfort_pack_options contains data. "
                    "Set has_comfort_pack to True if options are present."
                ),
                severity=ValidationSeverity.ERROR,
                category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                suggestion="Set has_comfort_pack to True.",
            )
        )

    # Rule 3: percentage plausibility
    for i, benefit in enumerate(bg.benefits):
        reimb = benefit.reimbursement
        if reimb.percentage is not None and (reimb.percentage < 0 or reimb.percentage > 600):
            all_errors.append(
                ValidationError(
                    field_path=f"benefits[{i}].reimbursement.percentage",
                    message=(
                        f"Percentage {reimb.percentage}% for '{benefit.benefit_name}' "
                        "is outside plausible range (0-600%). "
                        "French insurance reimbursements rarely exceed 500% BR."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.VALUE_PLAUSIBILITY,
                    suggestion="Verify the percentage against the raw_value in the document.",
                )
            )

    # Rule 4: fixed amounts plausibility
    for i, benefit in enumerate(bg.benefits):
        reimb = benefit.reimbursement
        if reimb.fixed_amount_euros is not None:
            if reimb.fixed_amount_euros < 0:
                all_errors.append(
                    ValidationError(
                        field_path=f"benefits[{i}].reimbursement.fixed_amount_euros",
                        message=(
                            f"Negative amount {reimb.fixed_amount_euros}€ "
                            f"for '{benefit.benefit_name}'."
                        ),
                        severity=ValidationSeverity.ERROR,
                        category=ValidationErrorCategory.VALUE_PLAUSIBILITY,
                    )
                )
            if reimb.fixed_amount_euros > 50000:
                all_errors.append(
                    ValidationError(
                        field_path=f"benefits[{i}].reimbursement.fixed_amount_euros",
                        message=(
                            f"Amount {reimb.fixed_amount_euros}€ for '{benefit.benefit_name}' "
                            "is unusually high for health insurance."
                        ),
                        severity=ValidationSeverity.WARNING,
                        category=ValidationErrorCategory.VALUE_PLAUSIBILITY,
                    )
                )

    # Rule 5: reimbursement type consistency with parsed values
    for i, benefit in enumerate(bg.benefits):
        reimb = benefit.reimbursement
        if (
            reimb.reimbursement_type == ReimbursementType.PERCENTAGE_BR_MINUS_SS
            and reimb.percentage is None
        ):
            all_errors.append(
                ValidationError(
                    field_path=f"benefits[{i}].reimbursement.percentage",
                    message=(
                        "Reimbursement type is 'percentage_br_minus_ss' "
                        f"but percentage is null for '{benefit.benefit_name}'. "
                        f"raw_value: '{reimb.raw_value}'."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion="Extract the percentage value from the raw_value.",
                )
            )
        if (
            reimb.reimbursement_type == ReimbursementType.FIXED_AMOUNT
            and reimb.fixed_amount_euros is None
        ):
            all_errors.append(
                ValidationError(
                    field_path=f"benefits[{i}].reimbursement.fixed_amount_euros",
                    message=(
                        f"Reimbursement type is 'fixed_amount' but fixed_amount_euros is null "
                        f"for '{benefit.benefit_name}'. raw_value: '{reimb.raw_value}'."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion="Extract the euro amount from the raw_value.",
                )
            )

    # Rule 6: "other" category must have detail
    for i, benefit in enumerate(bg.benefits):
        if benefit.category == CoverageCategory.OTHER and not benefit.category_detail:
            all_errors.append(
                ValidationError(
                    field_path=f"benefits[{i}].category_detail",
                    message=(
                        f"Benefit '{benefit.benefit_name}' has "
                        "category='other' but no category_detail."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion="Provide a category_detail explaining the non-standard category.",
                )
            )

    # Rule 7: "other" reimbursement type must have detail
    for i, benefit in enumerate(bg.benefits):
        reimb = benefit.reimbursement
        if (
            reimb.reimbursement_type == ReimbursementType.OTHER
            and not reimb.reimbursement_type_detail
        ):
            all_errors.append(
                ValidationError(
                    field_path=f"benefits[{i}].reimbursement.reimbursement_type_detail",
                    message=(
                        f"Benefit '{benefit.benefit_name}' has reimbursement_type='other' "
                        "but no reimbursement_type_detail."
                    ),
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.INTERNAL_CONSISTENCY,
                    suggestion=(
                        "Explain why the reimbursement format doesn't fit standard categories."
                    ),
                )
            )

    # Rule 8: coverage category diversity (a BG should cover multiple categories)
    if bg.benefits:
        categories = {b.category for b in bg.benefits}
        if len(categories) < 2:
            all_errors.append(
                ValidationError(
                    field_path="benefits",
                    message=(
                        f"Only {len(categories)} coverage category found: "
                        f"{[c.value for c in categories]}. "
                        "A guarantee table typically spans multiple categories "
                        "(routine care, hospitalization, optical, dental, hearing)."
                    ),
                    severity=ValidationSeverity.WARNING,
                    category=ValidationErrorCategory.COMPLETENESS,
                )
            )

    # Separate by severity
    errors = [e for e in all_errors if e.severity == ValidationSeverity.ERROR]
    warnings = [e for e in all_errors if e.severity == ValidationSeverity.WARNING]
    infos = [e for e in all_errors if e.severity == ValidationSeverity.INFO]

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        infos=infos,
    )


# ---------------------------------------------------------------------------
# Unified validation entry point
# ---------------------------------------------------------------------------


def validate_extraction(result: ExtractionResult) -> ValidationResult:
    """Validate an extraction result based on its document type.

    Args:
        result: The extraction result to validate.

    Returns:
        ValidationResult with all detected issues.
    """
    if result.extraction_errors:
        return ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="extraction",
                    message=f"Extraction failed: {'; '.join(result.extraction_errors)}",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.MISSING_CONTENT,
                )
            ],
        )

    if result.ipid is not None:
        return validate_ipid(result.ipid)
    elif result.guarantee_table is not None:
        return validate_guarantee_table(result.guarantee_table)
    else:
        return ValidationResult(
            is_valid=False,
            errors=[
                ValidationError(
                    field_path="extraction",
                    message="No extraction data found (both ipid and guarantee_table are None).",
                    severity=ValidationSeverity.ERROR,
                    category=ValidationErrorCategory.MISSING_CONTENT,
                )
            ],
        )
