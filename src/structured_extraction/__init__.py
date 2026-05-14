"""
Structured Data Extraction from Insurance Documents.

A pipeline for extracting structured data from APICIL insurance documents
using Claude API tool_use, with validation, retry, confidence scoring,
independent review, and batch processing.

CCA-F Scenario 6 implementation.
"""

from src.structured_extraction.batch import (
    BatchResults,
    BatchSubmission,
    build_batch_api_requests,
    calculate_batch_schedule,
    parse_batch_results,
    prepare_batch_requests,
)
from src.structured_extraction.confidence import (
    AccuracyTracker,
    ReviewDecision,
    route_for_review,
    stratified_sample,
)
from src.structured_extraction.document_loader import (
    InsuranceDocument,
    load_document,
    load_documents_from_directory,
)
from src.structured_extraction.extraction import (
    TokenUsage,
    extract_document,
)
from src.structured_extraction.retry import (
    ExtractionWithRetry,
    RetryConfig,
    extract_with_retry,
)
from src.structured_extraction.review import (
    QualityReviewResult,
    review_extraction,
)
from src.structured_extraction.schemas import (
    CoverageCategory,
    DocumentType,
    ExtractionResult,
    FieldConfidence,
    GuaranteeBenefit,
    GuaranteeTableExtraction,
    IPIDExtraction,
    ReimbursementLevel,
    ReimbursementType,
)
from src.structured_extraction.validation import (
    ValidationResult,
    validate_extraction,
)

__all__ = [
    # Schemas
    "CoverageCategory",
    "DocumentType",
    "ExtractionResult",
    "FieldConfidence",
    "GuaranteeBenefit",
    "GuaranteeTableExtraction",
    "IPIDExtraction",
    "ReimbursementLevel",
    "ReimbursementType",
    # Extraction
    "TokenUsage",
    "extract_document",
    # Validation
    "ValidationResult",
    "validate_extraction",
    # Retry
    "ExtractionWithRetry",
    "RetryConfig",
    "extract_with_retry",
    # Confidence
    "AccuracyTracker",
    "ReviewDecision",
    "route_for_review",
    "stratified_sample",
    # Review
    "QualityReviewResult",
    "review_extraction",
    # Batch
    "BatchResults",
    "BatchSubmission",
    "build_batch_api_requests",
    "calculate_batch_schedule",
    "parse_batch_results",
    "prepare_batch_requests",
    # Document loading
    "InsuranceDocument",
    "load_document",
    "load_documents_from_directory",
]
