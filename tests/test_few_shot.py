"""Tests for few-shot examples module.

CCA-F Task 4.2: few-shot examples for consistent output.
"""

from src.structured_extraction.few_shot import (
    GUARANTEE_TABLE_FEW_SHOT_EXAMPLES,
    IPID_FEW_SHOT_EXAMPLES,
    format_few_shot_examples,
    get_guarantee_table_few_shot_prompt,
    get_ipid_few_shot_prompt,
)


class TestFewShotExamples:
    """Test that few-shot examples are well-structured."""

    def test_ipid_examples_have_required_keys(self):
        for example in IPID_FEW_SHOT_EXAMPLES:
            assert "description" in example
            assert "input" in example
            assert "expected_output" in example
            assert "reasoning" in example

    def test_guarantee_table_examples_have_required_keys(self):
        for example in GUARANTEE_TABLE_FEW_SHOT_EXAMPLES:
            assert "description" in example
            assert "input" in example
            assert "expected_output" in example
            assert "reasoning" in example

    def test_ipid_examples_show_null_handling(self):
        """CCA-F Task 4.2: examples must demonstrate null for missing data."""
        null_example = IPID_FEW_SHOT_EXAMPLES[1]  # The "missing fields" example
        output = null_example["expected_output"]
        assert output["insurer_registration"] is None
        assert output["madelin_eligible"] is None

    def test_ipid_examples_show_reasoning_for_nulls(self):
        null_example = IPID_FEW_SHOT_EXAMPLES[1]
        assert "null" in null_example["reasoning"].lower()

    def test_guarantee_table_examples_show_varied_formats(self):
        """CCA-F Task 4.2: examples show diverse reimbursement formats."""
        format_example = GUARANTEE_TABLE_FEW_SHOT_EXAMPLES[0]
        benefits = format_example["expected_output"]["benefits"]
        types = {b["reimbursement"]["reimbursement_type"] for b in benefits}
        # Should cover multiple reimbursement types
        assert len(types) >= 2

    def test_guarantee_table_examples_handle_empty_cells(self):
        """CCA-F Task 4.2: examples show how to handle blank reimbursements."""
        empty_example = GUARANTEE_TABLE_FEW_SHOT_EXAMPLES[1]
        assert (
            "empty" in empty_example["reasoning"].lower()
            or "not covered" in empty_example["reasoning"].lower()
        )

    def test_at_least_2_examples_per_type(self):
        """CCA-F Task 4.2: 2-4 targeted examples recommended."""
        assert len(IPID_FEW_SHOT_EXAMPLES) >= 2
        assert len(GUARANTEE_TABLE_FEW_SHOT_EXAMPLES) >= 2


class TestFormatFewShotExamples:
    """Test prompt formatting of few-shot examples."""

    def test_ipid_prompt_not_empty(self):
        prompt = get_ipid_few_shot_prompt()
        assert len(prompt) > 100

    def test_guarantee_table_prompt_not_empty(self):
        prompt = get_guarantee_table_few_shot_prompt()
        assert len(prompt) > 100

    def test_prompt_contains_example_markers(self):
        prompt = get_ipid_few_shot_prompt()
        assert "Example 1" in prompt
        assert "Example 2" in prompt
        assert "INPUT" in prompt
        assert "EXPECTED EXTRACTION" in prompt
        assert "REASONING" in prompt

    def test_format_preserves_content(self):
        prompt = get_ipid_few_shot_prompt()
        assert "API Santé Équilibre" in prompt
        assert "302 927 553" in prompt

    def test_format_with_empty_list(self):
        result = format_few_shot_examples([])
        assert "examples" in result.lower()
