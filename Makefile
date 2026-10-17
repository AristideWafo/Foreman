.DEFAULT_GOAL := help
.PHONY: help install check check-full check-imports test fmt

BACKEND := cd backend && uv run

help: ## Liste les cibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Installe les dépendances
	cd backend && uv sync
	cd frontend && pnpm install --frozen-lockfile

fmt: ## Formate le code
	$(BACKEND) ruff format .
	$(BACKEND) ruff check --fix .
	cd frontend && pnpm format

check: ## Contrôles rapides (lint, format, typage, couches)
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .
	$(BACKEND) mypy
	$(MAKE) check-imports
	cd frontend && pnpm lint && pnpm format:check && pnpm typecheck

check-full: check ## Contrôles complets
	$(MAKE) test
	cd frontend && pnpm build

check-imports: ## Contrats de couches
	$(BACKEND) lint-imports

test: ## Tests
	$(BACKEND) pytest
	cd frontend && pnpm test
