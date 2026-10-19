.DEFAULT_GOAL := help
.PHONY: help install check check-full check-imports test fmt api-types check-api-types s01-fixture s02-fixture s10-fixture s11-fixture s12-fixture

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

api-types: ## Régénère openapi.json et les types TypeScript
	cd backend && uv run python scripts/export_openapi.py > ../openapi.json
	cd frontend && pnpm api-types

check-api-types: api-types ## Échoue si les types générés sont périmés
	git diff --exit-code -- openapi.json frontend/src/api/schema.d.ts

s01-fixture: ## Régénère le fixture des cartes S1 (événements normalisés) pour le front
	cd backend && uv run python scripts/export_s01_fixture.py > ../frontend/src/features/cards/s01-events.json
	cd frontend && pnpm exec prettier --write src/features/cards/s01-events.json

s02-fixture: ## Régénère le fixture des cartes S2 (clarification puis plan) pour le front
	cd backend && uv run python scripts/export_s02_fixture.py > ../frontend/src/features/cards/s02-events.json
	cd frontend && pnpm exec prettier --write src/features/cards/s02-events.json

s10-fixture: ## Régénère le fixture des cartes S10 (production sans droit : plan, approbation) pour le front
	cd backend && uv run python scripts/export_s10_fixture.py > ../frontend/src/features/cards/s10-events.json
	cd frontend && pnpm exec prettier --write src/features/cards/s10-events.json

s11-fixture: ## Régénère le fixture des cartes S11 (même demande rejouée : ressources déjà présentes) pour le front
	cd backend && uv run python scripts/export_s11_fixture.py > ../frontend/src/features/cards/s11-events.json
	cd frontend && pnpm exec prettier --write src/features/cards/s11-events.json

s12-fixture: ## Régénère le fixture des cartes S12 (plan invalidé : projet modifié) pour le front
	cd backend && uv run python scripts/export_s12_fixture.py > ../frontend/src/features/cards/s12-events.json
	cd frontend && pnpm exec prettier --write src/features/cards/s12-events.json
