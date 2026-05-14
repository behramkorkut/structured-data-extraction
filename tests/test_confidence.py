"""Tests for confidence scoring and human review routing.

CCA-F Task 5.5:
- Field-level confidence routing
- Accuracy tracking by document type and field
- Stratified random sampling
"""

from src.structured_extraction.confidence import (
    AccuracyTracker,
    ReviewDecision,
    route_for_review,
    stratified_sample,
)
from src.structured_extraction.schemas import (
    DocumentType,
    ExtractionResult,
    FieldConfidence,
    GuaranteeTableExtraction,
    IPIDExtraction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extraction(
    field_confidences: dict[str, FieldConfidence] | None = None,
    has_errors: bool = False,
    doc_type: DocumentType = DocumentType.IPID,
) -> ExtractionResult:
    if has_errors:
        return ExtractionResult(
            document_type=doc_type,
            source_file="test.pdf",
            extraction_errors=["API failed"],
        )

    return ExtractionResult(
        document_type=doc_type,
        source_file="test.pdf",
        ipid=IPIDExtraction(
            product_name="Test",
            insurer_name="Test",
            insurance_type="Test",
            covered_items=[],
            not_covered_items=[],
            exclusions=[],
            field_confidences=field_confidences,
        ),
    )


# ---------------------------------------------------------------------------
# Review routing tests
# ---------------------------------------------------------------------------


class TestRouteForReview:
    def test_all_high_confidence_auto_accept(self):
        """All HIGH fields → AUTO_ACCEPT."""
        result = _make_extraction(field_confidences=None)  # No low-confidence fields
        review = route_for_review(result)
        assert review.overall_decision == ReviewDecision.AUTO_ACCEPT
        assert review.needs_human_review is False

    def test_medium_confidence_needs_review(self):
        result = _make_extraction(
            field_confidences={"insurer_registration": FieldConfidence.MEDIUM}
        )
        review = route_for_review(result)
        assert review.overall_decision == ReviewDecision.HUMAN_REVIEW
        assert review.needs_human_review is True
        assert review.human_review_count == 1

    def test_low_confidence_needs_review(self):
        result = _make_extraction(field_confidences={"eligible_population": FieldConfidence.LOW})
        review = route_for_review(result)
        assert review.overall_decision == ReviewDecision.HUMAN_REVIEW
        assert review.reject_count == 1

    def test_not_found_confidence_needs_review(self):
        result = _make_extraction(
            field_confidences={"geographic_coverage": FieldConfidence.NOT_FOUND}
        )
        review = route_for_review(result)
        assert review.needs_human_review is True

    def test_extraction_errors_rejected(self):
        result = _make_extraction(has_errors=True)
        review = route_for_review(result)
        assert review.overall_decision == ReviewDecision.REJECT
        assert review.needs_human_review is True

    def test_mixed_confidences(self):
        result = _make_extraction(
            field_confidences={
                "insurer_registration": FieldConfidence.MEDIUM,
                "eligible_population": FieldConfidence.LOW,
            }
        )
        review = route_for_review(result)
        assert review.overall_decision == ReviewDecision.HUMAN_REVIEW
        assert review.human_review_count == 1  # MEDIUM
        assert review.reject_count == 1  # LOW

    def test_flagged_fields_contain_reason(self):
        result = _make_extraction(field_confidences={"product_name": FieldConfidence.MEDIUM})
        review = route_for_review(result)
        assert len(review.flagged_fields) == 1
        assert "product_name" in review.flagged_fields[0].reason

    def test_summary_format(self):
        result = _make_extraction()
        review = route_for_review(result)
        summary = review.summary()
        assert "test.pdf" in summary
        assert review.overall_decision in summary


# ---------------------------------------------------------------------------
# Accuracy tracker tests
# ---------------------------------------------------------------------------


class TestAccuracyTracker:
    def test_record_correct_extraction(self):
        tracker = AccuracyTracker()
        tracker.record("ipid", "product_name", is_correct=True)
        assert tracker.by_field["product_name"].accuracy_rate == 100.0

    def test_record_incorrect_extraction(self):
        tracker = AccuracyTracker()
        tracker.record("ipid", "product_name", is_correct=True)
        tracker.record("ipid", "product_name", is_correct=False)
        assert tracker.by_field["product_name"].accuracy_rate == 50.0

    def test_record_not_found(self):
        tracker = AccuracyTracker()
        tracker.record("ipid", "insurer_registration", is_correct=False, is_not_found=True)
        assert tracker.by_field["insurer_registration"].not_found_count == 1

    def test_accuracy_by_document_type(self):
        """CCA-F Task 5.5: per-type accuracy prevents masked poor performance."""
        tracker = AccuracyTracker()
        tracker.record("ipid", "product_name", is_correct=True)
        tracker.record("ipid", "product_name", is_correct=True)
        tracker.record("guarantee_table", "product_name", is_correct=True)
        tracker.record("guarantee_table", "product_name", is_correct=False)

        ipid_acc = tracker.get_accuracy_by_document_type("ipid")
        bg_acc = tracker.get_accuracy_by_document_type("guarantee_table")

        assert ipid_acc["product_name"] == 100.0
        assert bg_acc["product_name"] == 50.0

    def test_get_low_accuracy_fields(self):
        tracker = AccuracyTracker()
        for _ in range(9):
            tracker.record("ipid", "product_name", is_correct=True)
        tracker.record("ipid", "product_name", is_correct=False)  # 90% — at threshold

        for _ in range(7):
            tracker.record("ipid", "insurer_registration", is_correct=True)
        for _ in range(3):
            tracker.record("ipid", "insurer_registration", is_correct=False)  # 70%

        low_fields = tracker.get_low_accuracy_fields(threshold=90.0)
        field_names = [f.field_name for f in low_fields]
        assert "insurer_registration" in field_names
        assert "product_name" not in field_names  # 90% == threshold, not below

    def test_empty_tracker(self):
        tracker = AccuracyTracker()
        assert tracker.get_low_accuracy_fields() == []
        assert tracker.get_accuracy_by_document_type("ipid") == {}

    def test_no_extractions_returns_none_accuracy(self):
        tracker = AccuracyTracker()
        fa = tracker.by_field.get("nonexistent")
        assert fa is None


# ---------------------------------------------------------------------------
# Stratified sampling tests
# ---------------------------------------------------------------------------


class TestStratifiedSample:
    def test_sample_smaller_than_population(self):
        extractions = [_make_extraction(doc_type=DocumentType.IPID) for _ in range(10)]
        sample = stratified_sample(extractions, sample_size=5, seed=42)
        assert len(sample) <= 5

    def test_sample_larger_than_population_returns_all(self):
        extractions = [_make_extraction() for _ in range(3)]
        sample = stratified_sample(extractions, sample_size=10, seed=42)
        assert len(sample) == 3

    def test_stratified_by_document_type(self):
        """Sample should include both document types proportionally."""
        ipid_extractions = [
            ExtractionResult(
                document_type=DocumentType.IPID,
                source_file=f"ipid_{i}.pdf",
                ipid=IPIDExtraction(
                    product_name="Test",
                    insurer_name="Test",
                    insurance_type="Test",
                    covered_items=[],
                    not_covered_items=[],
                    exclusions=[],
                ),
            )
            for i in range(8)
        ]
        bg_extractions = [
            ExtractionResult(
                document_type=DocumentType.GUARANTEE_TABLE,
                source_file=f"bg_{i}.pdf",
                guarantee_table=GuaranteeTableExtraction(
                    product_name="Test",
                    guarantee_level="L1",
                    has_comfort_pack=False,
                    benefits=[],
                ),
            )
            for i in range(2)
        ]

        all_extractions = ipid_extractions + bg_extractions
        sample = stratified_sample(all_extractions, sample_size=5, seed=42)

        types_in_sample = [e.document_type for e in sample]
        assert DocumentType.IPID in types_in_sample
        assert DocumentType.GUARANTEE_TABLE in types_in_sample

    def test_reproducible_with_seed(self):
        extractions = [_make_extraction() for _ in range(20)]
        sample1 = stratified_sample(extractions, sample_size=5, seed=42)
        sample2 = stratified_sample(extractions, sample_size=5, seed=42)
        assert [e.source_file for e in sample1] == [e.source_file for e in sample2]

    def test_empty_input(self):
        sample = stratified_sample([], sample_size=5)
        assert sample == []
