# Plan — Semaine 3 : persistance visible, puis scénario S2 (clarification)

Plan écrit par l'agent `Plan` (Opus) puis **corrigé selon l'état réel de `prod`** (0.8.0). Tests back : unitaires,
peu nombreux et utiles (consigne du propriétaire). Skills de méthode : `backend-service-builder`,
`frontend-application-builder`, `doc-coauthoring` (jamais `docker-builder` sauf si `deploy/` est touché).

## État de départ (vérifié dans `prod`)

| Élément | État |
| --- | --- |
| `GET /api/projects` (récent d'abord, borné à 100), `ProjectStore.list` mémoire et PostgreSQL | **fait** (#150, 0.8.0) |
| `/healthz.persistence` (`postgres` ou `memory`, aucun détail de connexion) | **fait** (#150) |
| Front : menu lu depuis le serveur (`useProjects`), titre = début du message, suppression de `useRecentProjects` et des fichiers « … 2 » | **fait** (#150) |
| Badge « Mode mémoire » dans la barre latérale quand `/healthz` répond `memory` | **à faire** (absent du front) |
| Journal d'événements persisté (le chat est vidé à chaque redémarrage) | **à faire** : #150 le laisse explicitement de côté |
| Clarification (`ask_user`, carte, questions ouvertes), S2 | **à faire** |
| Tickets #27 et #31 : critères à aligner puis fermer | **à faire** |

Conséquence pour la persistance visible : après le déploiement de 0.8.0, `curl https://<domaine>/healthz` doit répondre
`"persistence":"postgres"` ; sinon `FOREMAN_DATABASE_URL` n'est pas lu. La liste des projets vient alors de la base.

## Décisions à trancher (recommandation en premier)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Historique du chat | **Journal persisté** (table `project_events`) ; le reconstruire perd les messages et rend S2 impossible |
| D2 | Contenu de `/healthz` (public) | Déjà tranché : seulement `persistence` (liste fermée) |
| D3 | Rétention | 1 000 événements par projet, élagage dans la même transaction |
| D4 | Messages en clair en base | Accepté pour le PoC, documenté ; chiffrement relève de #64 |
| D5 | Forme de la clarification | Outil `ask_user` (classe `control`, hors gateway) + route pour répondre ou reporter |
| D6 | Plan sans `environment` | Refusé (`invalid_plan`) ; suppression du repli `DEFAULT_ENVIRONMENT` |
| D7 | Interface `Provider` | Liste de `ConversationMessage(role, text)` maintenant (P2, glisse en S4 si besoin) |
| D8 | #27 et #31 | #27 : aligner la liste des codes (`approval_required` → S10 #36/#39, `drift_detected` → S5 #55, `denied` = `policy_denied`) puis fermer ; #31 : « S1 en mémoire + suite de contrat PostgreSQL » puis fermer |

## Volet agentique

- **Skills** : `docker-staging-deploy` et `gitlab-project-creation` gagnent la règle « si l'environnement ou la stack manquent,
  appeler `ask_user` avant tout plan » (leur `sha256` change : le fixture S1 est régénéré).
- **Référentiel** : `catalog/referentiels/project-schema.yaml` (`environment` obligatoire, `stack` facultatif). Les options viennent
  **du serveur** (`environments.yaml`), jamais du modèle.
- **Outil** : `ask_user` validé par Pydantic (`extra=forbid`) : au plus 5 questions, `field` pris dans le schéma, `prompt` ≤ 300
  caractères, identifiants de question générés par le serveur. Aucune écriture.
- **Matrice** : inchangée. **Provider** : `ReplayProvider.from_dir` (`s01.yaml` + `s02.yaml`, hash en double refusé, une seule entrée
  `default`), choix par sha256 exact du dernier message. **Budgets** : 3 tours de clarification par projet ; historique envoyé borné
  à 20 messages et 16 Kio. **Fakes** : aucun nouvel adaptateur.

## Volet back-end

- **Contrat (additif, `v: 1`)** : `CardData` gagne `ClarificationCardData{card_id, kind:"clarification", questions:[{id, field, prompt,
  options[], status: open|answered|deferred, answer?}]}` ; `POST /api/projects/{id}/questions/{question_id}` avec
  `{decision:"answer"|"defer", value?}` (202 réponse, 200 report, 404 y compris autre projet, 409 `turn_in_progress` ou
  `question_closed`, 422 opaque) ; nouveau code d'erreur `question_closed`.
- **Modules** : `core/clarification.py` (nouveau) ; `core/ports.py` (`set_open_questions`, `get_open_questions`, `ConversationMessage`) ;
  `core/turn.py` (historique, `ask_user`, refus de planifier si une question requise est ouverte) ; `core/planning.py` ;
  `infra/db/events.py` (`PostgresEventLog`) ; `infra/in_memory.py` ; `infra/replay_provider.py` ; `bootstrap/configure.py`.
- **Journal** : `UPDATE projects SET last_event_seq = last_event_seq + 1 RETURNING`, puis `INSERT`, puis élagage, dans une
  transaction ; diffusion aux abonnés sous un `asyncio.Lock` par projet (sinon seq 6 livré avant seq 5 la ferait perdre). Un seul
  processus : limite documentée.
- **Migration `0002_event_log`** (relecture propriétaire + revue indépendante) : `project_events(id identity, project_id FK, seq int > 0,
  turn_id uuid, type text, data jsonb, at timestamptz, UNIQUE(project_id, seq))`, `projects.last_event_seq`, index
  `projects(created_at desc)`.
- **Tests unitaires (au plus 2 par PR)** : journal (un second `EventLog` relit l'historique et continue à `seq+1` ; deux ajouts
  concurrents contigus) ; route de réponse (404 autre projet, 409 déjà répondue, 422 hors options sans écho, aucun tour lancé) ;
  plan sans environnement refusé ; `tests/e2e/test_s02_clarification.py` en mémoire (carte de clarification, aucun plan en base, puis
  réponse `staging` → carte plan `environment=staging`, fixture `s02-events.json` à jour).
- **Sécurité** : textes du modèle rendus en texte ; options imposées par le serveur ; erreurs opaques ; lectures filtrées par
  `project_id` ; aucun appel bloquant ; `/healthz` réduit à une énumération.

## Volet front-end (DESIGN.md d'abord)

- Badge d'avertissement « Mode mémoire » en pied de barre latérale, seulement si `/healthz` répond `memory`.
- `ClarificationCard` : questions, options (`toggle-group` ou `radio-group` shadcn), boutons **Répondre** et **Reporter** ; sur 409, on
  attend la carte réémise. Test de rendu léger sur `s02-events.json`. Types régénérés depuis l'OpenAPI.

## Pile de PR empilées (deux pistes : back séquentiel, front dès que le contrat est fusionné)

| PR | Branche (base) | Contenu | Ticket | Prio | Taille | Critère de fin observable |
| --- | --- | --- | --- | --- | --- | --- |
| ~~PR1/PR2/PR4~~ | — | ~~Liste des projets, `/healthz.persistence`, front serveur~~ | #150 | P0 | fait | `/healthz` renvoie `persistence` ; menu = projets du serveur |
| PR0 | `docs/plan-semaine-3` (prod) | Ce plan, ROADMAP, alignement de #27 et #31 | à créer | P0 | petite | Plan relu ; #27 et #31 fermés |
| PR-A | `feat/event-log-postgres` (prod) | Migration 0002, `PostgresEventLog`, `PERSISTENCE.md`, `DEPLOYMENT.md` | à créer | P0 | moyenne à grosse | Le chat d'un projet est intact après redéploiement sur env-perso ; test de contrat vert sur PostgreSQL en CI |
| PR-B | `feat/front-memory-badge` (prod) | Badge « Mode mémoire », DESIGN.md | à créer | P0 | petite | Le badge s'affiche seulement si `persistence = memory` |
| PR-C | `feat/contract-s3` (prod) | Contrat de clarification, route en 501, `question_closed`, types | à créer | P0 | petite | Contrôle de dérive OpenAPI vert |
| PR-D | `feat/clarification` (PR-A + PR-C) | `ask_user`, schéma, historique au provider, route réelle, `from_dir`, Skills, fixture S1 régénéré | #33 | P1 | grosse | `open_questions` relues après redémarrage ; tests de refus verts |
| PR-E | `test/s02-clarification` (PR-D) | Scénario S2, `s02.yaml`, `make s02-fixture` | #34 | P1 | moyenne | `test_s02_clarification.py` vert en CI |
| PR-F | `feat/front-clarification-card` (PR-C puis fixture de PR-E) | Carte de clarification, actions, test de rendu | #35 | P1 | moyenne | Carte rendue depuis `s02-events.json` |

Réaliste pour la semaine : PR0, PR-A, PR-B, PR-C (persistance et contrat), puis PR-D et PR-E. PR-F est la première à glisser en S4.

## Impact sur les contrats figés

Tout est additif (routes, champ `/healthz`, nouveau membre de l'union `kind`, nouveau code d'erreur) : **aucun passage en v2**.
Seule la durée de vie de `seq` change (durable en mode postgres). Un changement de **comportement** à signaler dans PR-D : un plan sans
environnement est refusé.

## Risques

- Verrou par projet indispensable pour l'ordre de diffusion ; plusieurs instances casseraient le direct (documenté).
- PR-D est la plus grosse ; si elle glisse, PR-A à PR-C suffisent à résoudre le problème de visibilité de la persistance.
- Les hash des Skills changent (fixture S1 à régénérer, sinon test rouge).
- Le texte canonique de la réponse doit être produit par la route, pas tapé (replay S2).
- Messages en clair en base (D4).

## Côté serveur (propriétaire)

1. `curl -fsS https://<domaine>/healthz` doit renvoyer `"persistence":"postgres"`.
2. Contrôle direct : `docker compose -p foreman exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select id,name,created_at from projects order by created_at desc limit 5"'`.
3. Après PR-A : un `pg_dump` est créé avant le déploiement ; pas de retour arrière d'image sans restaurer le dump.
4. Relire la migration 0002 et le `PostgresEventLog`. Clore #127, #105 et #32 avec une capture.

## Tickets à créer (jalon « PoC S3 », label de priorité, `## Critère de fin`)

Plan S3 (PR0), Journal d'événements persisté (PR-A, `area:migrations`), Front : badge mémoire (PR-B), Contrat S3 (PR-C), décision D7
(`type:decision`). Ajouter un `## Critère de fin` au format standard à #33 et #34.
