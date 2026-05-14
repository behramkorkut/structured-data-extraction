.PHONY: install test lint format run-single run-batch run-eval clean

install:
	uv sync --extra dev

test:
	uv run pytest tests/ -v --tb=short

test-cov:
	uv run pytest tests/ -v --tb=short --cov=src/structured_extraction --cov-report=term-missing

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

run-single:
	uv run python scripts/extract_single.py

run-batch:
	uv run python scripts/extract_batch.py

run-eval:
	uv run python scripts/run_evaluation.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache dist build *.egg-info
