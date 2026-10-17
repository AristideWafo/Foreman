# Persistance

PostgreSQL, SQLAlchemy 2 (async) et Alembic. _Pas encore implémentée : ce document fixe les règles._

- Le stockage appartient au domaine qui le possède (`projets`, `exécutions`, `registre`, `audit`) ; un sous-paquet `store/` par domaine.
- Un seul module backend (`infra/db`) gère le pool, les transactions (`BeginTx`) et la fermeture.
- Dépôts (requêtes) et migrations (DDL) sont séparés : `backend/migrations/` pour Alembic.
- **Un seul point d'entrée de migration par base.** Les migrations sont idempotentes, transactionnelles et sûres
  en démarrage concurrent : verrou consultatif `pg_advisory_lock` pris avant `alembic upgrade head`.
- Tests de migration (vrai PostgreSQL via testcontainers) : base vide, mise à jour depuis d'anciennes versions,
  double exécution, démarrage concurrent, rollback, reprise après crash.
- Un seul chemin d'import canonique ; l'ancien module est supprimé dans le même changement (pas de couche de compatibilité).
- Les secrets ne sont jamais stockés en clair : référence vers le magasin de secrets.
