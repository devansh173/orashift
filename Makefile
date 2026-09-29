.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup lint fmt test test-db check check-connections up down logs clean

help:  ## Show the available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the virtualenv and install all dependencies
	$(UV) sync --dev

lint:  ## Lint with ruff
	$(UV) run ruff check .

fmt:  ## Format with ruff
	$(UV) run ruff format .

test:  ## Run the unit tests (no database needed)
	$(UV) run pytest -m "not db"

test-db:  ## Run the tests that need live databases
	$(UV) run pytest -m db

check: lint  ## Everything CI runs: lint, format check, unit tests
	$(UV) run ruff format --check .
	$(UV) run pytest -m "not db"

check-connections:  ## Print the Oracle and PostgreSQL server versions
	$(UV) run orashift check-connections

up:  ## Start the bundled databases
	docker compose up -d

down:  ## Stop the bundled databases (volumes are kept)
	docker compose down

logs:  ## Follow the bundled database logs
	docker compose logs -f

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache build dist htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
