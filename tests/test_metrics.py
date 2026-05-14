"""Tests for pipeline metrics module."""

from src.structured_extraction.metrics import PipelineMetrics


class TestPipelineMetrics:
    def test_default_metrics(self):
        metrics = PipelineMetrics()
        assert metrics.total_documents == 0
        assert metrics.success_rate is None

    def test_success_rate_calculation(self):
        metrics = PipelineMetrics(
            total_documents=10,
            successfully_extracted=9,
        )
        assert metrics.success_rate == 90.0

    def test_first_try_rate(self):
        metrics = PipelineMetrics(
            successfully_extracted=8,
            valid_on_first_try=6,
        )
        assert metrics.first_try_rate == 75.0

    def test_summary_format(self):
        metrics = PipelineMetrics(
            run_id="test-001",
            total_documents=10,
            successfully_extracted=9,
            failed_extraction=1,
            valid_on_first_try=7,
            valid_after_retry=2,
            total_input_tokens=50000,
            total_output_tokens=15000,
            estimated_cost_usd=0.125,
        )
        summary = metrics.summary()
        assert "PIPELINE METRICS REPORT" in summary
        assert "test-001" in summary
        assert "9" in summary
        assert "$0.125" in summary

    def test_summary_with_no_data(self):
        metrics = PipelineMetrics()
        summary = metrics.summary()
        assert "N/A" in summary
