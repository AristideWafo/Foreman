# Persistance

Deux modes, choisis au démarrage par la présence de `FOREMAN_DATABASE_URL` (profils `web` et `worker` ; le CLI et les
évaluations restent en mémoire). `GET /healthz` annonce le mode : `"persistence":"postgres"` ou `"memory"`.

| Donnée | Mémoire | PostgreSQL |
| --- | --- | --- |
| Projets, plans, approbations, exécutions, registre, audit | perdus au redémarrage | tables de la migration `0001` |
| Chat (événements du flux d'un projet) | perdu au redémarrage | `project_events` (migration `0002`) |

## Journal d'événements

- **Contrat inchangé** : l'enveloppe v1 (`v`, `seq`, `project_id`, `turn_id`, `at`, `type`, `data`) est reconstruite à
  l'identique depuis `project_events`. `seq` est contigu à partir de 1 par projet et devient **durable** : après un
  redéploiement, le journal reprend à `seq + 1` et `Last-Event-ID` reste valable.
- **Ajout atomique** : une seule transaction fait `UPDATE projects SET last_event_seq = last_event_seq + 1 RETURNING`,
  l'`INSERT` de l'événement, puis l'élagage. La ligne du projet est verrouillée : deux ajouts concurrents obtiennent des
  `seq` contigus.
- **Diffusion** : après la validation, sous un `asyncio.Lock` par projet, pour que l'ordre de livraison soit l'ordre de
  `seq`. Aucun appel bloquant dans la boucle asynchrone.
- **Rétention** : les 1 000 derniers événements par projet (comme en mémoire) ; les plus anciens sont supprimés dans la
  même transaction que l'ajout. Un client qui reprend avant le plus ancien événement conservé reçoit ce qui reste.
- **Messages en clair** (décision D4, acceptée pour le PoC) : les textes des échanges, des cartes et des journaux
  d'exécution (déjà filtrés par la Tool Gateway) sont stockés non chiffrés dans `project_events.data`, donc aussi dans
  les `pg_dump`. Aucun secret ne doit y figurer. Le chiffrement relève du ticket #64.
- **Erreurs opaques** : un échec de base lève `StoreError("stockage indisponible")` ; ni SQL, ni paramètres, ni URL
  dans les journaux.

## Limites connues

- **Un seul processus.** Le verrou par projet et la liste des abonnés vivent en mémoire du processus. Avec plusieurs
  processus (réplicas, `web` + `worker` séparés), la base reste cohérente (`seq` contigu, garanti par la ligne du
  projet), mais un abonné ne voit en direct que les événements ajoutés par **son** processus : il rattrape les autres à
  la reconnexion. Une diffusion inter-processus (`LISTEN/NOTIFY`) est hors périmètre.
- Les projets existants avant `0002` repartent sans historique (le chat n'était qu'en mémoire).
- Une seule équipe (`dev`) : un `team_admin` voit et approuve tous les projets.

## Rôles et plafond d'autonomie (`0003_roles_autonomy`)

- `memberships(user_id, team_id, role)` (clé primaire `(user_id, team_id)`, rôle `developer`, `team_admin` ou
  `org_admin`) est **reconstruite à chaque démarrage** depuis `FOREMAN_DEV_MEMBERS` (la synchronisation remplace ;
  les lignes de `users` ne sont jamais supprimées). Identifiant utilisateur : `uuid5` du nom, stable.
- `plans.requested_by` reçoit l'identifiant du demandeur, posé par le serveur (vide pour les plans antérieurs).
- `executions.environment` est copié depuis `plans.content` ; les exécutions déjà présentes dont le plan n'a pas
  d'environnement sont rattachées à `staging`. Deux CHECK : `autonomy_level BETWEEN 1 AND 4` et
  `environment <> 'production' OR autonomy_level <= 3`. Si une ligne existante les viole, la migration échoue et
  ne modifie rien.
- `downgrade()` retire les CHECK, `environment` et `memberships` sans toucher aux plans, exécutions ni à l'audit.

## Exploitation

- **Sauvegarde** : `deploy-custom.sh --with-db` lance un `pg_dump -Fc` automatique avant chaque déploiement
  (voir [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Pas de retour arrière d'image sans restauration du dump** : les migrations `0002` et `0003` ne sont pas reconnues par une image plus
  ancienne. `downgrade()` supprime `project_events` ; il est refusé si la table contient des événements, sauf
  `FOREMAN_ALLOW_DESTRUCTIVE_DOWNGRADE=1` (même garde que `0001`).
- **Migrations** : `migrations/` exige une relecture du propriétaire et une revue indépendante.
