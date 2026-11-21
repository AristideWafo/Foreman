# Architecture

## Couches

```
surfaces (web API, cli)  ->  bootstrap  ->  tools, integrations  ->  core, infra  ->  config
```

| Couche | Rôle | Peut importer |
| --- | --- | --- |
| `surfaces` | API HTTP/SSE, CLI, webhooks entrants. Aucune logique d'agent. | `bootstrap`, `core`, `config` |
| `bootstrap` | Racine de composition : profils (`web`, `cli`, `worker`, `eval`), ordre de démarrage fixe. | tout ce qui est en dessous |
| `tools` | Outils neutres vis-à-vis des fournisseurs, `tools/crossvendor` pour les combinaisons. | `core`, `config` |
| `integrations` | Un paquet par fournisseur (config, vérification, client, outils, identifiants). | `core`, `config` |
| `core` | Domaine, `TurnService`, boucle d'agent, budgets, ports (interfaces). | `config` |
| `infra` | Implémentations des ports : base de données, queue, secrets, SSH, runner. | `core` (interfaces), `config` |
| `config` | Constantes, noms de variables d'environnement. Feuille. | rien |

Règles : pairs sans import mutuel (`tools` ↔ `integrations`, `surfaces` ↔ cli/web entre eux) ;
`core` définit les interfaces, `infra` les implémente, jamais l'inverse.

## Flux d'un tour

1. Une surface reçoit la demande et la transmet au `TurnService`.
2. Chaîne commune : identité → droits du demandeur → approbation si requise.
3. La boucle d'agent appelle le fournisseur de modèle (`Provider`) et les outils via la Tool Gateway.
4. Budgets : appels, temps, coût et tokens de contexte (logs injectés).
5. Événements diffusés en SSE ; actions journalisées dans l'audit.

## Fournisseur de modèle (`Provider`)

`bootstrap/provider.py` choisit l'adaptateur : rejeu forcé en CI et en profil EVAL (aucun réseau), rejeu
tant qu'aucune clé ni modèle n'est saisi, sinon le fournisseur réel désigné par le réglage `llm.provider`,
relu à chaque appel (ADR 0004) :

| Valeur | Adaptateur | État |
| --- | --- | --- |
| `anthropic` (défaut, absent ou inconnu) | `integrations/anthropic` (SDK `anthropic`) | défaut et repli |
| `strands` | `integrations/strands` (Strands Agents, couche modèle seulement) | **non validé en réel** (aucune clé sur le serveur) |

Bascule : `foreman llm set-provider --provider strands` (retour : `--provider anthropic`), sans
redémarrage. Le modèle se choisit avec `foreman llm set-model --model claude-opus-5-5` (liste de
`integrations/anthropic/models.yaml`). Strands n'exécute aucun outil : les appels d'outils reviennent au
`TurnService`, qui passe par la gateway.

## Tool Gateway (`core/gateway`, `core/policy`)

Le moteur n'atteint un adaptateur que par le port `Gateway.call(GatewayCall)` ; `bootstrap/adapters.py`
est le seul endroit qui importe les connecteurs. Dix contrôles, chacun ne pouvant que refuser :
contexte, outil connu, schéma, matrice (`policy/matrix.evaluate`, pure, refus par défaut),
approbations (plan `dev_approved`, hash du plan, appel identique à l'étape du plan), invariants et
périmètre (environnement du plan, parent ou cible dans le registre DU projet), budget, exécution
sous délai, filtrage de la sortie (secrets masqués, 4 Kio, 50 lignes de 500 caractères), audit.
Le contexte exige un bail valide (propriétaire et époque), une étape réservée (`running`) et les
étapes antérieures réussies ; un même appel n'est jamais exécuté deux fois en parallèle. Les erreurs
(`CallDenied`, `CallFailed`) ne portent qu'un code stable, sans exception d'origine. Audit : une ligne
`allow` avant l'exécution, une ligne `denied` ou `error` pour un refus ou un échec ; l'appel exécuté
rend sa ligne `executed` et les ressources CRÉÉES au moteur, qui les écrit avec l'étape
(`complete_step`).

## Décisions

Les décisions structurantes sont consignées dans `docs/adr/`.
