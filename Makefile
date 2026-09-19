.PHONY: help install hooks lint format test up down check-db validate

help:  ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install:  ## Install the package with dev tools
	pip install -e ".[dev]"

hooks:  ## Enable git pre-commit hooks (needs a git repository: run `git init` first)
	pre-commit install

lint:  ## Check code style without changing files
	ruff check .
	ruff format --check .

format:  ## Auto-fix style problems
	ruff check --fix .
	ruff format .

test:  ## Run all tests with coverage
	pytest

up:  ## Start PostgreSQL in the background
	docker compose up -d --wait db

down:  ## Stop PostgreSQL (data is kept in a Docker volume)
	docker compose down

check-db:  ## Verify the pipeline container can reach PostgreSQL
	docker compose run --rm pipeline check-db

validate:  ## Clean the staging data and run the data-quality checks
	pipeline validate
