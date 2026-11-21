# ADR 0004 — Strands Agents comme couche modèle, la gateway reste le seul chemin

**Statut** : proposé (relecture du propriétaire en attente — ticket #345)

## Contexte

Le propriétaire veut faire passer le runtime LLM du `AnthropicProvider` écrit à la main (SDK `anthropic`)
au SDK **Strands Agents** (`strands-agents`), avec Claude Opus (`claude-opus-5-5`) comme modèle configuré.

Strands sait faire deux choses : parler à un modèle (`Model.stream`) et piloter une boucle d'agent
(`strands.Agent`, outils `@tool`, exécution des outils par Strands). Or Foreman exige que :

- le `TurnService` possède la boucle de tour, les budgets (`TurnMeter`), l'approbation de plan et la boucle
  d'outils plafonnée à 5 tours ;
- la Tool Gateway soit le **seul** chemin vers les outils (matrice, masquage, aliasing, audit — ADR 0003).

## Décision

**Strands est utilisé uniquement comme couche modèle/streaming, derrière le port `Provider`.**

- `integrations/strands/provider.py` : `StrandsProvider.complete` ouvre un modèle Strands pour l'appel
  (`strands.models.anthropic.AnthropicModel`, client créé puis fermé), appelle `Model.stream(messages,
  tool_specs, system_prompt)` et agrège les événements (texte, blocs `toolUse`, arrêt, usage) en `ModelReply`.
- **Interdit** : `strands.Agent`, `@tool`, `strands.tools`, les outils MCP de Strands, les `anthropic_tools`
  (outils côté serveur). Strands ne reçoit que des **spécifications** d'outils ; il n'a aucun handler à
  exécuter. Les blocs `toolUse` reviennent au `TurnService`, qui appelle `Gateway.read` comme avant.
- Mêmes outils (`propose_plan`, `ask_user`, lectures du catalogue), même prompt, mêmes noms `to_wire`,
  même enveloppe `untrusted_data` que `AnthropicProvider`.
- Sans état : clé et modèle relus du `SecretStore` à chaque appel, jamais de l'environnement. Aucune
  exception de Strands ou du SDK ne sort : seul le type est journalisé, `ProviderFailed` (message fixe,
  désormais dans `core/llm.py`) remonte et le tour échoue en `internal_error`. Les journaux DEBUG de Strands
  (qui citent la requête) sont coupés.

### Alternative écartée

Enregistrer des outils Strands dont le handler délègue à `Gateway.read` et laisser `strands.Agent` boucler :
la boucle d'outils passerait dans Strands. Budgets par appel, plafond de 5 tours, carte « droit manquant »
qui arrête le tour, aliasing et masquage des résultats sortiraient du `TurnService` ou devraient y être
recâblés par des hooks — deux boucles à garder cohérentes, et un chemin d'exécution hors de notre code.

## Sélection et bascule

- Réglage `llm.provider` (`anthropic` | `strands`), stocké comme le modèle dans le magasin de secrets,
  relu **à chaque appel** (`SwitchedProvider`, `bootstrap/provider_switch.py`) : pas de redémarrage.
- **Défaut : `anthropic`** (absent ou valeur inconnue). `AnthropicProvider` reste disponible comme repli.
- Bascule : `foreman llm set-provider --provider strands` ; retour : `--provider anthropic`.
- Pas de repli silencieux : une erreur de Strands ne retombe ni sur Anthropic ni sur le rejeu.
- CI et profil EVAL : inchangés, le rejeu est forcé, aucun appel réseau.

## Non validé

**Aucun appel réel n'a été fait** : il n'y a pas de clé LLM sur le serveur. Les tests utilisent un faux
modèle Strands (flux d'événements scriptés). Le défaut reste `anthropic` tant qu'un appel Opus via Strands
n'a pas été validé avec une vraie clé (un tour S1 et un tour avec lecture GitLab).

## Conséquences

- Dépendance `strands-agents[anthropic]==1.65.0` (épinglée ; 1.64.0 et avant plafonnent `anthropic<1.0`,
  incompatible avec `anthropic==1.17.0`). Elle tire boto3, opentelemetry, watchdog et `mcp` : `mcp` n'est
  jamais importé par Foreman (test de structure de l'ADR 0003).
- Strands ne transmet pas `strict: true` des outils : `propose_plan` n'est plus garanti conforme par l'API ;
  la validation par schéma du `TurnService` reste l'autorité.
- `foreman llm record` enregistre toujours via `AnthropicProvider` (réponse brute de l'API Messages).

## À revoir si

- Strands est validé en réel : passer le défaut à `strands` puis supprimer `AnthropicProvider` (pas de couche
  de compatibilité durable) ;
- un besoin de la boucle d'agent Strands apparaît (il faudrait alors une nouvelle ADR).
