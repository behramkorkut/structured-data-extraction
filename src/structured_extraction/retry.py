"""
Retry-with-error-feedback loop for extraction quality improvement.

CCA-F Scenario 6, Task 4.4:
- On validation failure, append specific validation errors to the retry prompt
- Claude receives the original document, its failed extraction, AND the error feedback
- Retries are only attempted for retryable errors (not missing content)
- Maximum retry attempts prevent infinite loops

This implements the "retry-with-error-feedback" pattern from the exam guide:
the model sees its previous extraction alongside the specific errors,
enabling targeted self-correction rather than blind re-extraction.
"""

from dataclasses import dataclass, field

from anthropic import Anthropic

from src.structured_extraction.extraction import (
    TokenUsage,
    extract_document,
)
from src.structured_extraction.schemas import ExtractionResult
from src.structured_extraction.validation import (
    ValidationResult,
    validate_extraction,
)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------


@dataclass
class RetryConfig:
    """Configuration for the retry loop.

    Attributes:
        max_retries: Maximum number of retry attempts. The exam guide warns
            against arbitrary iteration caps as primary stopping — our primary
            stop is "validation passes". max_retries is a safety net.
        retry_only_on_retryable: If True, skip retry when all errors are
            non-retryable (e.g., MISSING_CONTENT). Saves API cost.
    """

    max_retries: int = 2
    retry_only_on_retryable: bool = True


# ---------------------------------------------------------------------------
# Retry attempt record
# ---------------------------------------------------------------------------


@dataclass
class RetryAttempt:
    """Record of a single extraction attempt for debugging/auditing."""

    attempt_number: int
    result: ExtractionResult
    validation: ValidationResult
    was_retried: bool
    retry_reason: str | None = None


@dataclass
class ExtractionWithRetry:
    """Final result of the extraction-validation-retry pipeline.

    Contains the best extraction result along with the full audit trail
    of attempts for debugging and metrics.
    """

    final_result: ExtractionResult
    final_validation: ValidationResult
    attempts: list[RetryAttempt] = field(default_factory=list)
    total_attempts: int = 0

    @property
    def succeeded_on_first_try(self) -> bool:
        return self.total_attempts == 1 and self.final_validation.is_valid

    @property
    def required_retry(self) -> bool:
        return self.total_attempts > 1

    @property
    def is_valid(self) -> bool:
        return self.final_validation.is_valid

    def summary(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"Extraction: {status} | "
            f"Attempts: {self.total_attempts} | "
            f"Errors: {self.final_validation.error_count} | "
            f"Warnings: {self.final_validation.warning_count}"
        )


# ---------------------------------------------------------------------------
# Retry-with-feedback prompt builder
# ---------------------------------------------------------------------------


def build_retry_prompt(
    original_text: str,
    document_type: str,
    source_file: str,
    previous_extraction: ExtractionResult,
    validation_feedback: str,
) -> str:
    """Build a retry prompt that includes the original document,
    the failed extraction, and specific validation errors.

    CCA-F Task 4.4: "appending specific validation errors to the prompt
    on retry to guide the model toward correction"

    The model sees:
    1. The original document (source of truth)
    2. Its previous extraction (what it got wrong)
    3. Specific validation errors (what to fix)

    Args:
        original_text: The original document text.
        document_type: Document type string.
        source_file: Source filename.
        previous_extraction: The failed extraction result.
        validation_feedback: Formatted validation error feedback.

    Returns:
        The complete retry prompt string.
    """
    # Serialize the previous extraction for context
    if previous_extraction.ipid is not None:
        prev_json = previous_extraction.ipid.model_dump_json(indent=2)
    elif previous_extraction.guarantee_table is not None:
        prev_json = previous_extraction.guarantee_table.model_dump_json(indent=2)
    else:
        prev_json = "{}"

    return (
        f"You previously extracted data from this document but there were validation errors.\n"
        f"Please re-extract, correcting the specific issues listed below.\n\n"
        f"--- VALIDATION ERRORS ---\n"
        f"{validation_feedback}\n"
        f"--- END VALIDATION ERRORS ---\n\n"
        f"--- YOUR PREVIOUS EXTRACTION ---\n"
        f"{prev_json}\n"
        f"--- END PREVIOUS EXTRACTION ---\n\n"
        f"--- ORIGINAL DOCUMENT ---\n"
        f"Document type: {document_type}\n"
        f"Source file: {source_file}\n\n"
        f"{original_text}\n"
        f"--- END DOCUMENT ---\n\n"
        f"Now re-extract the data, fixing the validation errors listed above. "
        f"For fields where information is genuinely not in the document, return null."
    )


# ---------------------------------------------------------------------------
# Main retry loop
# ---------------------------------------------------------------------------


def extract_with_retry(
    text_content: str,
    document_type: str,
    source_file: str,
    client: Anthropic | None = None,
    model: str = "claude-haiku-4-5",
    token_usage: TokenUsage | None = None,
    config: RetryConfig | None = None,
) -> ExtractionWithRetry:
    """Extract structured data with validation-retry loop.

    Pipeline:
    1. Extract → Validate
    2. If valid → return
    3. If invalid AND retryable → retry with error feedback
    4. If invalid AND not retryable → return (no point retrying)
    5. Repeat up to max_retries

    Args:
        text_content: Document text to extract from.
        document_type: Detected document type.
        source_file: Source filename.
        client: Anthropic client (created from env if None).
        model: Claude model to use.
        token_usage: Optional token tracker.
        config: Retry configuration. Defaults to RetryConfig().

    Returns:
        ExtractionWithRetry with final result and attempt audit trail.
    """
    if config is None:
        config = RetryConfig()

    attempts: list[RetryAttempt] = []
    current_text = text_content
    is_retry = False
    previous_result: ExtractionResult | None = None
    previous_validation: ValidationResult | None = None

    for attempt_num in range(1, config.max_retries + 2):  # +2: 1 initial + max_retries
        # --- Build the prompt ---
        if is_retry and previous_result is not None and previous_validation is not None:
            # Retry: include previous extraction and validation errors
            prompt_text = build_retry_prompt(
                original_text=text_content,
                document_type=document_type,
                source_file=source_file,
                previous_extraction=previous_result,
                validation_feedback=previous_validation.get_feedback_for_retry(),
            )
        else:
            # First attempt: just the document
            prompt_text = current_text

        # --- Extract ---
        result = extract_document(
            text_content=prompt_text,
            document_type=document_type,
            source_file=source_file,
            client=client,
            model=model,
            token_usage=token_usage,
        )

        # --- Validate ---
        validation = validate_extraction(result)

        # --- Record attempt ---
        retry_reason = None
        if is_retry:
            retry_reason = (
                f"Retry due to {previous_validation.error_count} validation errors"
                if previous_validation
                else "Retry"
            )

        attempts.append(
            RetryAttempt(
                attempt_number=attempt_num,
                result=result,
                validation=validation,
                was_retried=is_retry,
                retry_reason=retry_reason,
            )
        )

        # --- Decide: stop or retry ---
        if validation.is_valid:
            # Success — no need to retry
            break

        if attempt_num > config.max_retries:
            # Exhausted retries
            break

        if config.retry_only_on_retryable and not validation.has_retryable_errors:
            # All errors are non-retryable (missing content) — no point retrying
            break

        # --- Prepare for retry ---
        is_retry = True
        previous_result = result
        previous_validation = validation

    return ExtractionWithRetry(
        final_result=attempts[-1].result,
        final_validation=attempts[-1].validation,
        attempts=attempts,
        total_attempts=len(attempts),
    )
