.DEFAULT_GOAL := help
.PHONY: help install check check-full check-imports test

help: ## Liste les cibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Installe les dépendances
	@echo "Rien à installer pour l'instant (le backend arrive en PR 02, le frontend en PR 03)."

check: ## Contrôles rapides
	@echo "Aucun contrôle configuré pour l'instant."

check-full: check ## Contrôles complets
	@$(MAKE) test

check-imports: ## Contrats de couches
	@echo "Contrats de couches ajoutés en PR 02."

test: ## Tests
	@echo "Aucun test pour l'instant."
