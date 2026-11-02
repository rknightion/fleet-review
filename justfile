set shell := ["bash", "-euo", "pipefail", "-c"]

# List the available recipes.
default:
    @just --list

# Install the project and dev dependencies.
setup:
    uv sync

# Format the code with ruff.
[group('dev')]
fmt:
    uv run ruff format .

# Fail if any file needs formatting.
[group('check')]
fmt-check:
    uv run ruff format --check .

# Lint with ruff.
[group('check')]
lint:
    uv run ruff check .

# Run the test suite.
[group('check')]
test:
    uv run pytest

# Pre-commit gate: formatting, lint and tests.
[group('check')]
check: fmt-check lint test
