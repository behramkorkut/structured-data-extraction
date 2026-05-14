"""
Field-level confidence scoring and human review routing.

CCA-F Scenario 6, Task 5.5:
- Field-level confidence scores calibrated using labeled validation sets
- Stratified random sampling for measuring error rates
- Routing extractions with low confidence to human review
- Analyzing accuracy by document type and field

Confidence is assigned by Claude during extraction (in field_confidences),
then validated and calibrated here using labeled data.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field

from src.structured_extraction.schemas import (
    ExtractionResult,
    FieldConfidence,
)

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------


@dataclass
class ConfidenceThresholds:
    """Thresholds for routing decisions based on confidence.

    Attributes:
        auto_accept_threshold: Fields at or above this confidence are auto-accepted.
        human_review_threshold: Fields below this confidence are routed to human review.
        reject_threshold: Fields below this are flagged as likely incorrect.
    """

    auto_accept_threshold: FieldConfidence = FieldConfidence.HIGH
    human_review_threshold: FieldConfidence = FieldConfidence.MEDIUM
    reject_threshold: FieldConfidence = FieldConfidence.LOW


# ---------------------------------------------------------------------------
# Review routing decision
# ---------------------------------------------------------------------------


class ReviewDecision:
    """Routing decision for an extraction result."""

    AUTO_ACCEPT = "auto_accept"
    HUMAN_REVIEW = "human_review"
    REJECT = "reject"


@dataclass
class FieldReviewItem:
    """A single field flagged for human review."""

    field_name: str
    confidence: FieldConfidence
    decision: str  # ReviewDecision value
    reason: str


@dataclass
class ExtractionReviewResult:
    """Review routing result for a complete extraction."""

    source_file: str
    overall_decision: str  # ReviewDecision value
    flagged_fields: list[FieldReviewItem] = field(default_factory=list)
    auto_accepted_count: int = 0
    human_review_count: int = 0
    reject_count: int = 0

    @property
    def needs_human_review(self) -> bool:
        return self.overall_decision in (ReviewDecision.HUMAN_REVIEW, ReviewDecision.REJECT)

    def summary(self) -> str:
        return (
            f"Review [{self.source_file}]: {self.overall_decision} | "
            f"Auto: {self.auto_accepted_count} | "
            f"Review: {self.human_review_count} | "
            f"Reject: {self.reject_count}"
        )


# ---------------------------------------------------------------------------
# Confidence-based routing
# ---------------------------------------------------------------------------


def route_for_review(
    result: ExtractionResult,
    thresholds: ConfidenceThresholds | None = None,
) -> ExtractionReviewResult:
    """Route an extraction result for human review based on field confidence.

    CCA-F Task 5.5: routing extractions with low model confidence
    to human review, prioritizing limited reviewer capacity.

    Decision logic:
    - If ANY field has LOW or NOT_FOUND confidence → HUMAN_REVIEW
    - If all fields are HIGH → AUTO_ACCEPT
    - If mix of HIGH and MEDIUM → HUMAN_REVIEW (conservative)
    - If extraction failed → REJECT

    Args:
        result: The extraction result with field_confidences.
        thresholds: Optional custom thresholds.

    Returns:
        ExtractionReviewResult with routing decision and flagged fields.
    """
    if thresholds is None:
        thresholds = ConfidenceThresholds()

    # Handle extraction errors
    if result.extraction_errors:
        return ExtractionReviewResult(
            source_file=result.source_file,
            overall_decision=ReviewDecision.REJECT,
            reject_count=1,
            flagged_fields=[
                FieldReviewItem(
                    field_name="extraction",
                    confidence=FieldConfidence.NOT_FOUND,
                    decision=ReviewDecision.REJECT,
                    reason=f"Extraction failed: {result.extraction_errors[0]}",
                )
            ],
        )

    # Get field confidences from the extraction
    field_confidences = _get_field_confidences(result)

    flagged_fields = []
    auto_count = 0
    review_count = 0
    reject_count = 0

    for field_name, confidence in field_confidences.items():
        if confidence == FieldConfidence.HIGH:
            auto_count += 1
        elif confidence == FieldConfidence.MEDIUM:
            review_count += 1
            flagged_fields.append(
                FieldReviewItem(
                    field_name=field_name,
                    confidence=confidence,
                    decision=ReviewDecision.HUMAN_REVIEW,
                    reason=f"Field '{field_name}' has medium confidence — verify against source.",
                )
            )
        elif confidence in (FieldConfidence.LOW, FieldConfidence.NOT_FOUND):
            reject_count += 1
            flagged_fields.append(
                FieldReviewItem(
                    field_name=field_name,
                    confidence=confidence,
                    decision=ReviewDecision.REJECT,
                    reason=(
                        f"Field '{field_name}' has {confidence.value} confidence"
                        " — likely incorrect or missing."
                    ),
                )
            )

    # Overall decision: worst-case wins
    if reject_count > 0 or review_count > 0:
        overall = ReviewDecision.HUMAN_REVIEW
    else:
        overall = ReviewDecision.AUTO_ACCEPT

    return ExtractionReviewResult(
        source_file=result.source_file,
        overall_decision=overall,
        flagged_fields=flagged_fields,
        auto_accepted_count=auto_count,
        human_review_count=review_count,
        reject_count=reject_count,
    )


def _get_field_confidences(result: ExtractionResult) -> dict[str, FieldConfidence]:
    """Extract field confidence map from an ExtractionResult.

    If the extraction doesn't include field_confidences (all HIGH),
    returns an empty dict — meaning all fields are auto-accepted.
    """
    if result.ipid is not None and result.ipid.field_confidences:
        return result.ipid.field_confidences
    elif result.guarantee_table is not None and result.guarantee_table.field_confidences:
        return result.guarantee_table.field_confidences
    return {}


# ---------------------------------------------------------------------------
# Accuracy tracking by document type and field
# ---------------------------------------------------------------------------


@dataclass
class FieldAccuracy:
    """Accuracy metrics for a specific field across documents."""

    field_name: str
    total_extractions: int = 0
    correct_extractions: int = 0
    incorrect_extractions: int = 0
    not_found_count: int = 0

    @property
    def accuracy_rate(self) -> float | None:
        """Accuracy as a percentage, or None if no extractions."""
        if self.total_extractions == 0:
            return None
        return (self.correct_extractions / self.total_extractions) * 100


@dataclass
class AccuracyTracker:
    """Track extraction accuracy by document type and field.

    CCA-F Task 5.5: analyzing accuracy by document type and field
    to verify consistent performance across all segments.

    The exam warns that aggregate accuracy (e.g., 97% overall) may mask
    poor performance on specific document types or fields.
    """

    # field_name → FieldAccuracy
    by_field: dict[str, FieldAccuracy] = field(default_factory=dict)
    # document_type → field_name → FieldAccuracy
    by_type_and_field: dict[str, dict[str, FieldAccuracy]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def record(
        self,
        document_type: str,
        field_name: str,
        is_correct: bool,
        is_not_found: bool = False,
    ) -> None:
        """Record an extraction result for a specific field.

        Args:
            document_type: Type of document (e.g., "ipid", "guarantee_table").
            field_name: Name of the field extracted.
            is_correct: Whether the extraction matches ground truth.
            is_not_found: Whether the field was not found in the document.
        """
        # By field
        if field_name not in self.by_field:
            self.by_field[field_name] = FieldAccuracy(field_name=field_name)
        fa = self.by_field[field_name]
        fa.total_extractions += 1
        if is_not_found:
            fa.not_found_count += 1
        elif is_correct:
            fa.correct_extractions += 1
        else:
            fa.incorrect_extractions += 1

        # By type and field
        if field_name not in self.by_type_and_field[document_type]:
            self.by_type_and_field[document_type][field_name] = FieldAccuracy(field_name=field_name)
        tfa = self.by_type_and_field[document_type][field_name]
        tfa.total_extractions += 1
        if is_not_found:
            tfa.not_found_count += 1
        elif is_correct:
            tfa.correct_extractions += 1
        else:
            tfa.incorrect_extractions += 1

    def get_low_accuracy_fields(self, threshold: float = 90.0) -> list[FieldAccuracy]:
        """Find fields with accuracy below threshold.

        CCA-F Task 5.5: aggregate metrics may mask poor field performance.
        """
        return [
            fa
            for fa in self.by_field.values()
            if fa.accuracy_rate is not None and fa.accuracy_rate < threshold
        ]

    def get_accuracy_by_document_type(self, document_type: str) -> dict[str, float | None]:
        """Get per-field accuracy for a specific document type."""
        if document_type not in self.by_type_and_field:
            return {}
        return {
            field_name: fa.accuracy_rate
            for field_name, fa in self.by_type_and_field[document_type].items()
        }


# ---------------------------------------------------------------------------
# Stratified random sampling
# ---------------------------------------------------------------------------


def stratified_sample(
    extractions: list[ExtractionResult],
    sample_size: int,
    seed: int | None = None,
) -> list[ExtractionResult]:
    """Select a stratified random sample for quality measurement.

    CCA-F Task 5.5: stratified random sampling of high-confidence
    extractions for ongoing error rate measurement and novel pattern detection.

    Stratifies by document type to ensure each type is represented
    proportionally in the sample.

    Args:
        extractions: All extraction results.
        sample_size: Total number of samples to draw.
        seed: Random seed for reproducibility.

    Returns:
        Stratified sample of extraction results.
    """
    if seed is not None:
        random.seed(seed)

    if len(extractions) <= sample_size:
        return list(extractions)

    # Group by document type
    by_type: dict[str, list[ExtractionResult]] = defaultdict(list)
    for ext in extractions:
        by_type[ext.document_type.value].append(ext)

    # Calculate proportional sample size per type
    sample: list[ExtractionResult] = []
    for _doc_type, type_extractions in by_type.items():
        proportion = len(type_extractions) / len(extractions)
        type_sample_size = max(1, round(proportion * sample_size))
        type_sample_size = min(type_sample_size, len(type_extractions))

        type_sample = random.sample(type_extractions, type_sample_size)
        sample.extend(type_sample)

    # Trim to exact sample size if rounding caused overshoot
    if len(sample) > sample_size:
        sample = random.sample(sample, sample_size)

    return sample
