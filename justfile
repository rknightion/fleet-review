set shell := ["bash", "-euo", "pipefail", "-c"]

# List the available recipes.
default:
    @just --list

# Install the project and dev dependencies.
setup:
    uv sync

# Prepare locked dependencies and the duplication tool for Cursor Cloud.
[group('dev')]
[script('bash')]
cloud-bootstrap:
    set -euo pipefail
    uv sync --locked --no-python-downloads --compile-bytecode
    version="$(uv run --locked python -c 'from fleet_review.duplication import DEFAULT_JSCPD_VERSION; print(DEFAULT_JSCPD_VERSION)')"
    npx --yes --prefer-offline "jscpd@$version" --version

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
