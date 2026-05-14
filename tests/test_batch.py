"""Tests for batch processing module.

CCA-F Task 4.5:
- Message Batches API: 50% cost savings
- custom_id for request/response correlation
- Failure handling by custom_id
- SLA calculation
"""

from src.structured_extraction.batch import (
    BatchDocumentRequest,
    BatchResultItem,
    BatchResults,
    BatchSubmission,
    build_batch_api_requests,
    calculate_batch_schedule,
    parse_batch_results,
    prepare_batch_requests,
)

# ---------------------------------------------------------------------------
# Prepare batch tests
# ---------------------------------------------------------------------------


class TestPrepareBatchRequests:
    def test_prepare_single_document(self):
        documents = [
            {
                "custom_id": "doc-001",
                "document_type": "ipid",
                "source_file": "ipid_test.pdf",
                "text_content": "Document content...",
            }
        ]
        submission = prepare_batch_requests(documents)
        assert submission.total_documents == 1
        assert submission.requests[0].custom_id == "doc-001"

    def test_prepare_multiple_documents(self):
        documents = [
            {
                "custom_id": f"doc-{i:03d}",
                "document_type": "ipid" if i % 2 == 0 else "guarantee_table",
                "source_file": f"doc_{i}.pdf",
                "text_content": f"Content {i}",
            }
            for i in range(5)
        ]
        submission = prepare_batch_requests(documents)
        assert submission.total_documents == 5

    def test_custom_ids_preserved(self):
        """CCA-F Task 4.5: custom_id for request/response correlation."""
        documents = [
            {
                "custom_id": "my-unique-id-123",
                "document_type": "ipid",
                "source_file": "test.pdf",
                "text_content": "content",
            },
        ]
        submission = prepare_batch_requests(documents)
        assert submission.requests[0].custom_id == "my-unique-id-123"


# ---------------------------------------------------------------------------
# Build API requests tests
# ---------------------------------------------------------------------------


class TestBuildBatchApiRequests:
    def test_request_format(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="ipid",
                    source_file="test.pdf",
                    text_content="Document text",
                ),
            ],
        )
        api_requests = build_batch_api_requests(submission)

        assert len(api_requests) == 1
        req = api_requests[0]
        assert req["custom_id"] == "doc-001"
        assert "params" in req
        assert req["params"]["model"] == "claude-haiku-4-5"
        assert len(req["params"]["tools"]) == 2  # Both extraction tools
        assert len(req["params"]["messages"]) == 1

    def test_ipid_uses_forced_tool_choice(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="ipid",
                    source_file="test.pdf",
                    text_content="content",
                ),
            ],
        )
        api_requests = build_batch_api_requests(submission)
        assert api_requests[0]["params"]["tool_choice"] == {"type": "tool", "name": "extract_ipid"}

    def test_unknown_type_uses_any(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="unknown",
                    source_file="test.pdf",
                    text_content="content",
                ),
            ],
        )
        api_requests = build_batch_api_requests(submission)
        assert api_requests[0]["params"]["tool_choice"] == {"type": "any"}

    def test_system_prompt_included(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="ipid",
                    source_file="test.pdf",
                    text_content="content",
                ),
            ],
        )
        api_requests = build_batch_api_requests(submission)
        assert "system" in api_requests[0]["params"]


# ---------------------------------------------------------------------------
# Parse batch results tests
# ---------------------------------------------------------------------------


class TestParseBatchResults:
    def test_parse_successful_result(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="ipid",
                    source_file="test.pdf",
                    text_content="content",
                ),
            ],
        )
        raw_results = [
            {
                "custom_id": "doc-001",
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "extract_ipid",
                                "input": {
                                    "product_name": "Test",
                                    "insurer_name": "Test",
                                    "insurance_type": "Test",
                                    "covered_items": [],
                                    "not_covered_items": [],
                                    "exclusions": [],
                                },
                            }
                        ],
                    },
                },
            }
        ]

        results = parse_batch_results(raw_results, submission)
        assert results.success_count == 1
        assert results.failure_count == 0
        assert results.items[0].extraction_result.ipid.product_name == "Test"

    def test_parse_failed_result(self):
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001",
                    document_type="ipid",
                    source_file="test.pdf",
                    text_content="content",
                ),
            ],
        )
        raw_results = [
            {
                "custom_id": "doc-001",
                "result": {
                    "type": "errored",
                    "error": {"message": "Rate limit exceeded"},
                },
            }
        ]

        results = parse_batch_results(raw_results, submission)
        assert results.failure_count == 1
        assert results.items[0].error == "Rate limit exceeded"

    def test_failed_custom_ids_for_resubmission(self):
        """CCA-F Task 4.5: identify failed items by custom_id for resubmission."""
        submission = BatchSubmission(
            requests=[
                BatchDocumentRequest(
                    custom_id="doc-001", document_type="ipid", source_file="a.pdf", text_content="a"
                ),
                BatchDocumentRequest(
                    custom_id="doc-002", document_type="ipid", source_file="b.pdf", text_content="b"
                ),
                BatchDocumentRequest(
                    custom_id="doc-003", document_type="ipid", source_file="c.pdf", text_content="c"
                ),
            ],
        )
        raw_results = [
            {
                "custom_id": "doc-001",
                "result": {
                    "type": "succeeded",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "extract_ipid",
                                "input": {
                                    "product_name": "A",
                                    "insurer_name": "A",
                                    "insurance_type": "A",
                                    "covered_items": [],
                                    "not_covered_items": [],
                                    "exclusions": [],
                                },
                            }
                        ]
                    },
                },
            },
            {
                "custom_id": "doc-002",
                "result": {"type": "errored", "error": {"message": "Timeout"}},
            },
            {
                "custom_id": "doc-003",
                "result": {"type": "errored", "error": {"message": "Context too long"}},
            },
        ]

        results = parse_batch_results(raw_results, submission)
        assert results.failed_custom_ids == ["doc-002", "doc-003"]
        assert results.success_count == 1
        assert results.failure_count == 2

    def test_batch_results_summary(self):
        results = BatchResults(
            items=[
                BatchResultItem(custom_id="doc-001", is_success=True),
                BatchResultItem(custom_id="doc-002", is_success=False, error="Failed"),
            ],
            total_submitted=2,
        )
        summary = results.summary()
        assert "1/2 succeeded" in summary
        assert "Failed: 1" in summary


# ---------------------------------------------------------------------------
# SLA calculation tests
# ---------------------------------------------------------------------------


class TestCalculateBatchSchedule:
    def test_basic_schedule(self):
        """CCA-F Task 4.5: calculate submission timing for SLA."""
        schedule = calculate_batch_schedule(
            total_documents=500,
            batch_size=1000,
            max_batch_processing_hours=24,
            sla_hours=30,
        )
        assert schedule["num_batches"] == 1
        assert schedule["buffer_hours"] == 6
        assert schedule["cost_savings_percent"] == 50

    def test_multiple_batches(self):
        schedule = calculate_batch_schedule(
            total_documents=2500,
            batch_size=1000,
        )
        assert schedule["num_batches"] == 3

    def test_tight_sla(self):
        schedule = calculate_batch_schedule(
            total_documents=100,
            sla_hours=26,
            max_batch_processing_hours=24,
        )
        assert schedule["buffer_hours"] == 2

    def test_recommendation_text(self):
        schedule = calculate_batch_schedule(total_documents=100)
        assert "50%" in schedule["recommendation"]
        assert "batch" in schedule["recommendation"].lower()
