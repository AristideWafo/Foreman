# Plan — Semaine 1 : squelette de bout en bout

Établi par un agent Opus d'après le code de `prod` (commit `7ae49e2`), contrôlé par un sous-agent Haiku sur les
tickets du jalon 1, exécuté par Sonnet. Objectif : un message dans le chat, un faux agent, un flux d'événements,
une carte affichée, un déploiement sur `env-perso`. Hors périmètre : base de données, authentification (S10),
vrai modèle, gateway, Skills, plan haché, approbations, audit.

## Contrat figé v1

Erreurs HTTP opaques, toujours `{"error": "<code>"}` : `not_found` (404), `invalid_request` (422, sans écho de la
saisie), `capacity_exceeded` (503), `internal_error` (500), `not_implemented` (501, tant que la route est un stub).

| Méthode | Chemin | Corps | Réponse |
| --- | --- | --- | --- |
| GET | `/healthz` | – | inchangée |
| POST | `/api/projects` | `{"title"?: str ≤ 120}` | 201 `Project{id, title, created_at}` |
| GET | `/api/projects/{id}` | – | 200 `Project` ou 404 |
| POST | `/api/projects/{id}/messages` | `{"text": str 1..4000}` | 202 `{"turn_id"}` (asynchrone dans le contrat) |
| GET | `/api/projects/{id}/events?after=<seq>` | en-tête `Last-Event-ID` prioritaire | `text/event-stream` : rejoue au-delà de `after`, puis le direct |

**Trame SSE.** `id: <seq>` (reprise native d'EventSource), pas de champ `event:` (un seul `onmessage`, le type est
dans le JSON), `data:` = l'enveloppe.

**Enveloppe `Event`** (union discriminée sur `type`, définie dans `backend/src/foreman/core/events.py`, publiée dans
`openapi.json` sous `components.schemas.Event`) : `{v: 1, seq, project_id, turn_id, at, type, data}`.

| `type` | `data` | Émis en semaine 1 |
| --- | --- | --- |
| `message` | `{role: "user" \| "assistant", text}` | oui |
| `card` | `{card_id, kind: "plan", title, summary, steps: [{seq, title, status}]}` | oui |
| `execution_step` | `{card_id, seq, status}` | déclaré, émis à partir de S1 (semaine 2) |
| `turn_status` | `{status: "running" \| "completed" \| "failed"}` | oui |
| `error` | `{code: "internal_error" \| "unknown_tool", message}` (texte générique) | en cas d'échec |

**Évolution.** Un ajout (nouveau `type`, nouveau `kind` de carte, champ optionnel) garde `v: 1` ; tout autre changement
passe à `v: 2`. Le front ignore les types inconnus.

**Authentification du flux.** Même domaine (la SPA est servie par le backend) : l'`EventSource` natif suffit.
Semaine 1 : aucune identité (`user_id="web-anonymous"`). Semaine 4 : cookie de session `HttpOnly; Secure; SameSite=Strict`.

## Volets

- **Agentique.** `ModelReply` gagne `tool_calls`. `ScriptedProvider` (infra) répond « Reçu : … » et appelle `propose_plan`
  (3 étapes `pending`). Le `TurnService` valide `propose_plan` puis émet une `card` ; tout autre outil devient
  `error/unknown_tool` et n'est **jamais exécuté** (future place de la gateway). `EchoProvider` est supprimé.
- **Back-end.** `core/events.py`, `core/projects.py`, ports `ProjectStore` et `EventLog`, stockage en mémoire borné
  (100 projets, 1 000 événements par projet, file de 100 par abonné), routes `/api`, SSE avec reprise, erreurs opaques,
  repli SPA. Un seul worker uvicorn.
- **Front-end.** Client typé par les types générés, hook `useProjectEvents` (EventSource ouvert avant le POST,
  dédoublonnage par `seq`), pages d'accueil et de projet, composant `Card`, test de rendu léger.
- **Infra.** Fusionner #100 puis #102 (conflit probable sur `deploy.yml`), `release-please` sur `prod` (#23).

## PR empilées

| PR | Branche | Contenu | Ticket | Dépend de |
| --- | --- | --- | --- | --- |
| P1 | `feat/contract-v1` | contrat : événements, schémas, routes en 501, `openapi.json`, types | #17 | – |
| P2 | `feat/turn-messages` | mémoire, `ScriptedProvider`, `TurnService`, POST, repli SPA | #18 | P1 |
| P3 | `feat/sse-events` | GET `/events`, reprise, abonnés | #19 | P2 |
| P4 | `feat/front-chat-card` | chat et carte | #20 | P1 |
| D1 | `docs/spec-python` | spec : Go vers Python | #24 | – |

Deux pistes au plus : back (P2 puis P3) et front (P4), sur le contrat fusionné de P1.

## Risques et décisions du propriétaire

1. `env-perso` est public et sans authentification : `basicAuth` Traefik proposé (#106).
2. `CODEOWNERS` attribue `*` au propriétaire seul : il ne peut pas approuver ses propres PR (#22).
3. Visibilité du paquet GHCR : public, ou jeton sur le serveur (#105).
4. Validation du contrat v1 : tout changement non additif passe ensuite à `v: 2`.
5. Compression Traefik et SSE : à vérifier avec `curl -N` (#105).
6. `openapi-typescript` et le schéma de flux : repli prévu par fusion dans `components` (c'est ce qui est fait).
7. État en mémoire perdu à chaque déploiement (accepté), donc un seul worker.
