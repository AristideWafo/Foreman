# CLAUDE.md

Lisez `AGENTS.md` : c'est la source de vérité pour les commandes, les couches, la sécurité et le workflow Git.
Ce fichier ajoute la **méthode de travail**. Priorité : livrer, **mais en restant structuré** — couches,
sécurité et contrats ne se négocient pas, le reste est proportionné au PoC puis à la v1.

## Avant de démarrer une feature ou une semaine

Ne codez pas avant d'avoir écrit le **plan complet**, dans le ticket ou la description de PR. Il couvre
les trois volets, même si l'un d'eux ne change pas (dites-le alors) :

| Volet | À préciser |
| --- | --- |
| **Agentique** | Skills et référentiels touchés, outils et leur classe/réversibilité, règles de la matrice, `Provider`, budgets, fakes et réponses rejouées |
| **Back-end** | Modules par couche, migrations, contrats d'API et d'événements, gateway, tests, points de sécurité |
| **Front-end** | Écrans et cartes, événements consommés, types générés depuis l'OpenAPI |

Le plan liste aussi : ce qui est **ajouté**, **modifié**, **supprimé**, l'impact sur les contrats figés,
les risques, et le **critère de fin** observable de la feature.

## Qui fait quoi (modèles)

| Étape | Modèle | Rôle |
| --- | --- | --- |
| Plan | **Opus** (agent `Plan`) | Conçoit le plan complet ci-dessus |
| Vérification des tickets | **Haiku** (sous-agent) | Contrôle, ne code pas — voir ci-dessous |
| Exécution | **Sonnet** | Implémente le plan, écrit les tests |
| Évaluation | **Sonnet ou Opus** | Compare le résultat au critère de fin du ticket, pas à l'intention |

Utilisez le paramètre `model` de l'outil `Agent`. Si un modèle n'est pas disponible, dites-le et
n'enchaînez pas silencieusement avec un autre.

## Vérification des tickets (sous-agent Haiku)

Une fois le plan écrit et avant d'exécuter, un sous-agent Haiku vérifie sur GitHub (REST : `gh api repos/{owner}/{repo}/issues`) :

1. **Existence** : chaque élément du plan a un ticket ; sinon il liste ceux à créer.
2. **Priorité** : un label `priority:P0` à `P3` et un jalon.
3. **Définition** : un `## Critère de fin` **observable** (un test qui passe, un scénario vert en CI, une carte
   visible, un document relu) — pas « implémenter X ».
4. **Cohérence** : pas de doublon, dépendances et ordre plausibles.

Il rapporte les écarts, il ne corrige rien lui-même. Une feature **sans priorité ni critère de fin ne démarre pas**.

## Priorités

| Label | Sens |
| --- | --- |
| `priority:P0` | Chemin critique du jalon en cours : sans lui, rien d'autre n'avance |
| `priority:P1` | Cœur du PoC, nécessaire à la démonstration |
| `priority:P2` | Important, ne bloque pas la démonstration |
| `priority:P3` | v1 ou confort |

On travaille dans l'ordre P0, P1, P2, P3. Un scénario est **fini** quand il passe en CI **et** que sa carte
est affichée dans le front.

## Tests et sécurité

- **Back-end : toujours des tests** avec chaque fonctionnalité (à fort signal, fakes nommés — voir `AGENTS.md`).
- **Front-end : les tests sont facultatifs** (ils coûtent cher). Au minimum, vérifiez qu'une carte s'affiche
  (test de rendu léger, ou vérification notée dans la PR) pour prouver le critère de fin d'un scénario.
- **Sécurité** : à chaque changement, vérifiez les règles de `AGENTS.md` (pas de secret en clair, erreurs
  opaques, gateway comme seul chemin, aucun appel bloquant dans la boucle asynchrone). Pour `gateway/`,
  `policy/` et `migrations/`, relecture propriétaire (CODEOWNERS).
- Pour le PoC et la v1, ne cherchez pas l'exhaustivité (couverture, audits poussés) : livrez, sans casser
  les couches ni les contrats.

## Rythme

Au plus **deux pistes en parallèle** (par exemple moteur et front), sur des **contrats figés** (OpenAPI et
schéma d'événements committés, vérifiés en CI). Les tests (couches, scénarios rejoués) relisent en premier.
En fin de feature : mettre à jour le ticket (cocher le critère de fin, fermer) et `docs/ROADMAP.md` si le plan a changé.
