.DEFAULT_GOAL := help
UV ?= uv

.PHONY: help setup lint fmt test test-db check check-connections seed reseed generate verify dataset eval check-notebooks train-kaggle kaggle-status ora2pg-pull up down logs clean

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

check: lint  ## Everything CI runs: lint, format check, notebooks, unit tests
	$(UV) run ruff format --check .
	$(UV) run python scripts/check_notebooks.py
	$(UV) run pytest -m "not db"

check-connections:  ## Print the Oracle and PostgreSQL server versions
	$(UV) run orashift check-connections

seed:  ## Load the schemas and seed data into both databases, then verify
	$(UV) run orashift seed

reseed:  ## Regenerate the seed CSVs from the fixed seed, then load and verify
	$(UV) run orashift seed --regenerate

generate:  ## Build the Oracle source-unit pool and verify it against Oracle
	$(UV) run orashift generate --show-failures

verify:  ## Translate every unit and verify it by execution on both engines
	$(UV) run orashift verify --show-failures

train-kaggle:  ## Push the training notebook to Kaggle, wait, and fetch results
	$(UV) run python scripts/kaggle_run.py push --wait

kaggle-status:  ## Check on the running Kaggle notebook
	$(UV) run python scripts/kaggle_run.py status

eval:  ## Score predictions by execution and write metrics, report and charts
	$(UV) run orashift eval

check-notebooks:  ## Statically validate the Kaggle notebooks
	$(UV) run python scripts/check_notebooks.py

dataset:  ## Build the train/val/test JSONL splits and the dataset card
	$(UV) run orashift build-dataset

ora2pg-pull:  ## Fetch the pinned ora2pg image used for the DDL baseline
	docker pull --platform linux/amd64 georgmoser/ora2pg:latest

up:  ## Start the bundled databases
	docker compose up -d

down:  ## Stop the bundled databases (volumes are kept)
	docker compose down

logs:  ## Follow the bundled database logs
	docker compose logs -f

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache build dist htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
