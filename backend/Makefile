.PHONY: help install install-dev install-ubuntu lint format check clean test

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install main dependencies
	pip install -e .

install-dev:  ## Install development dependencies
	pip install -e ".[dev]"

install-windows:  ## Install Windows-specific dependencies (includes pywin32)
	pip install -e ".[windows]"

install-ubuntu:  ## Install Ubuntu-specific dependencies (excludes Windows packages)
	pip install -e ".[ubuntu]"

lint:  ## Run flake8 linting
	flake8 src/

format:  ## Format code with black and isort
	black src/
	isort src/

check:  ## Run all code quality checks
	black --check src/
	isort --check-only src/
	flake8 src/
	mypy src/

clean:  ## Clean up Python cache files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

test:  ## Run tests
	pytest tests/

setup-precommit:  ## Install pre-commit hooks
	pre-commit install

update-precommit:  ## Update pre-commit hooks
	pre-commit autoupdate
