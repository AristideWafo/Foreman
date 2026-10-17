# ADR 0001 — Stack

**Statut** : accepté

- Backend Python 3.12+, uv, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL.
- Frontend React + TypeScript + Vite, Tailwind, shadcn/ui, TanStack Query.
- Exécution via `ansible-runner`, SSH via `asyncssh`.
- Contrat API : OpenAPI FastAPI → types TypeScript générés.

**Pourquoi Python** : le projet est surtout réseau, I/O et orchestration ; `ansible-runner` et Pydantic sont natifs Python.
**Coût** : discipline de typage (mypy strict sur la gateway) et aucun appel bloquant dans la boucle asynchrone.
