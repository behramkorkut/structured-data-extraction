---
paths:
  - "tests/**/*.py"
---

# Testing Conventions

- All tests must use mocked Anthropic API responses (no real API calls)
- Use `pytest.fixture` for shared test data and mock responses
- Use `pytest.mark.parametrize` for boundary and edge case testing
- Test both success paths and all error categories
- Name test functions descriptively: `test_<what>_<condition>_<expected>`
- Keep tests deterministic — no randomness, no network calls
