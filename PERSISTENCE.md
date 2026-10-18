# Persistance

PostgreSQL, SQLAlchemy 2 (async, Core) et Alembic. Implémentée pour les projets, plans, approbations, exécutions,
registre et audit ; les événements du chat restent en mémoire.

- Le stockage appartient au domaine qui le possède. Les ports sont dans `core/store.py` (`PlanStore`, `ExecutionStore`,
  `ResourceRegistry`, `AuditLog`) et `core/ports.py` (`ProjectStore`) ; `infra/db/` les implémente en PostgreSQL et
  `infra/in_memory.py` en mémoire (CLI, tests unitaires). Une suite de tests de contrat commune
  (`tests/store_contract/`) tourne sur les deux.
- Un seul module backend (`infra/db`) gère le pool, les transactions (`async with engine.begin()`) et la fermeture.
- Dépôts (requêtes) et migrations (DDL) sont séparés : `backend/migrations/` pour Alembic. `infra/db/tables.py` décrit
  le même schéma en SQLAlchemy Core ; un test d'autogénération échoue si les deux divergent.
- Requêtes paramétrées uniquement. Toute lecture est cloisonnée par `project_id` : une ressource d'un autre projet est
  absente (404), jamais interdite.
- Le temps (bails, expirations) est celui de la base (`now()`), jamais celui de l'application.
- **Un seul point d'entrée de migration par base** (`infra/db/migrate.py: upgrade_head`). Les migrations sont
  idempotentes, transactionnelles et sûres en démarrage concurrent : verrou consultatif `pg_advisory_lock` pris avant
  `alembic upgrade head`. L'application les applique au démarrage du profil web (hors boucle asynchrone,
  `asyncio.to_thread`).
- Tests de migration sur un vrai PostgreSQL 16 : **la CI utilise un service PostgreSQL** (job `backend-tests`,
  variable `FOREMAN_TEST_DATABASE_URL`), pas testcontainers. Chaque test reçoit une base neuve, créée puis supprimée.
  En local : lancer un PostgreSQL et exporter `FOREMAN_TEST_DATABASE_URL` ; sans elle, les tests PostgreSQL sont
  ignorés (et échouent si `CI=true`). Couverts : base vide, double exécution, deux `upgrade` concurrents, retour
  arrière jusqu'à la base puis nouvel `upgrade`, journal d'audit append-only, contraintes d'unicité et clés composites.
  Pas encore : mise à jour depuis d'anciennes versions (une seule révision existe) et reprise après crash en cours de
  migration (le DDL transactionnel annule tout).
- Un seul chemin d'import canonique ; l'ancien module est supprimé dans le même changement (pas de couche de compatibilité).
- Les secrets ne sont jamais stockés en clair : référence vers le magasin de secrets. L'URL de la base vient de
  `FOREMAN_DATABASE_URL` et n'est jamais journalisée.
- Limite connue : le rôle de l'application possède `audit_events` et peut supprimer ses déclencheurs ; des rôles
  séparés sont prévus en v1.0.
