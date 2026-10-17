# Feuille de route des PR empilées

| PR | Branche | Contenu |
| --- | --- | --- |
| 01 | `pr/01-foundations` | AGENTS.md, gouvernance, Makefile, docs d'architecture |
| 02 | `pr/02-backend-skeleton` | Backend uv, couches, import-linter, ruff, mypy, pytest |
| 03 | `pr/03-frontend-skeleton` | Vite + React + TS, Tailwind, Vitest, ESLint |
| 04 | `pr/04-ci` | Workflow `ci.yml` (jobs parallèles, contrat API OpenAPI → TS). Service PostgreSQL et tests de migration : à l'arrivée de la persistance |
| 05 | `pr/05-security` | `security.yml`, Dependabot |
| 06 | `pr/06-build-deploy` | `build.yml`, `deploy.yml`, `deploy/` (Dockerfile, compose, Caddy, `deploy.sh`), release-please |
| 07 | `pr/07-ops-docs` | PERSISTENCE, CI, `evals.yml`, `.env*.example`, guide d'intégration |

## Ensuite (hors de cette pile)

Persistance (Alembic + testcontainers), Tool Gateway et politique, boucle d'agent, intégrations, runner Ansible, auth OIDC.
