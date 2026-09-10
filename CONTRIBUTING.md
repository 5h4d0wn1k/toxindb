# Contributing to toxindb

Thank you for your interest in contributing to toxindb.

## Development Setup

```bash
git clone https://github.com/5h4d0wn1k/toxindb.git
cd toxindb
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/ -v
```

## Code Standards

- Python 3.10+, stdlib-only core (no external runtime dependencies).
- All public functions must have type hints.
- All heuristics must have corresponding tests.
- New heuristics require both a poison-trace test (fires) and clean-trace test (quiet).
- Follow existing code style; no comments unless asked.

## Pull Requests

1. Fork and create a feature branch.
2. Add tests for new functionality.
3. Ensure `pytest tests/ -v` passes with 0 failures.
4. Keep commits focused and well-described.
5. Open a PR against `main`.

## Heuristic Naming Convention

All heuristics follow the pattern `TX-NNN` where NNN is a zero-padded number.
When adding a new heuristic, increment from the highest existing number.
