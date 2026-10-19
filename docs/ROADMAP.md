# Feuille de route

Source : `dev platform .md` (décisions D1 à D15, scénarios S1 à S12, étapes du PoC). Les éléments marqués
**(proposition)** ne viennent pas de la spec. Les tickets correspondants sont dans le projet GitHub
« Foreman — PoC et v1 ».

## Avancement

~~Barré~~ = terminé et vérifié. **En cours** = travail commencé. Les tickets portent la même information
(étiquettes `statut:en-cours` et `statut:termine`).

| Étape | État |
| --- | --- |
| ~~Phase 0 — squelette du dépôt~~ | terminée |
| ~~Semaine 1 — squelette de bout en bout~~ | code et déploiement terminés ; authentification en ligne vérifiée (#106) ; **reste à vérifier** : flux SSE derrière Traefik (#105) |
| Semaine 2 — scénario S1 | code fusionné dans `prod` (0.5.0 à 0.6.0) : persistance PostgreSQL, gateway, moteur, approbation, cartes ; ~~#127 (persistance après redéploiement) et #32 (carte vue) fermés~~ ; #27 et #31 : critères à aligner |
| ~~Semaine 3 — scénario S2~~ | code terminé et fusionné dans `prod` (0.9.0) : journal d'événements persisté (migration 0002), badge « Mode mémoire », clarification (`ask_user`, questions ouvertes), scénario S2 et carte de clarification ; **reste à vérifier** sur env-perso : chat intact après redéploiement (#127), `/healthz` → `persistence: postgres` |
| ~~Semaine 4 — scénario S10~~ | code terminé et fusionné dans `prod` (#167 à #172) : matrice R1 à R10, rôles et authentification de développement (migration 0003), approbation administrateur, scénario S10 et carte d'approbation ; **reste** : PR-G (suivi de la revue du journal, #176), badge de rôle dans la barre latérale, contrôle serveur Traefik avant `proxy_header` |
| Semaines 5 et 6, essai jetable, fournisseurs réels, scénarios d'échec, évaluation | à venir |

## ~~Phase 0 — Squelette du dépôt (terminée)~~

~~PR #1 à #7 : couches imposées par import-linter, CI, sécurité, build signé, déploiement par digest,
règles pour les agents. Aucune logique métier : `TurnService` et `/healthz` seulement.~~

## Méthode

1. **Squelette de bout en bout d'abord.** Un message dans le chat, un faux agent, un flux d'événements,
   une carte affichée, un déploiement en staging. Tout le reste s'accroche à ce squelette.
2. **Un scénario par semaine** : S1, puis S2, S10, S11, S12. Critère de fin : le scénario passe en CI **et**
   la carte correspondante est affichée dans le front.
3. **Adaptateurs simulés d'abord.** Les scénarios tournent sur des fakes nommés et un modèle rejoué ;
   les vrais fournisseurs viennent après (leurs prérequis externes ne bloquent pas le début).
4. **Deux pistes en parallèle au maximum** (par exemple moteur et front), **contrats figés** : schéma OpenAPI
   et schéma des événements committés, vérifiés en CI. Au-delà de deux pistes, la relecture se dégrade.
5. **Les tests relisent d'abord** : frontières de couches, scénarios rejoués. L'attention humaine va à la
   Tool Gateway, à la matrice de droits et aux migrations, relues avec une attention particulière (`CODEOWNERS` est désactivé pour l'instant : revue indépendante par un agent à la place).
6. **Essai jetable avant les vrais outils serveur** : le script de bootstrap et le wrapper Compose, jamais
   exécutés, sont testés sur un conteneur SSH local. Le résultat est un compte rendu, pas du code à garder.

## PoC

Réussi quand 20 exécutions nominales de suite passent, dont 5 avec un échec injecté à la quatrième étape
reprises sans doublon, et que S1 à S12 passent sans régression. Critères complémentaires : zéro écriture hors
registre, zéro secret dans les logs envoyés au modèle (contrôle automatique), chaque exécution reconstituable
depuis le journal.

| Étape | Contenu | Fin de l'étape |
| --- | --- | --- |
| ~~**Semaine 1 — Squelette**~~ | ~~Chat dans le front, `POST` d'un message, faux agent derrière `Provider`, flux SSE d'événements typés, une carte affichée, déploiement automatique en staging. Figer l'OpenAPI et le schéma d'événements.~~ **Reste :** vérifier le flux SSE derrière Traefik (#105), l'authentification en ligne (#106), protéger `prod` (#22). | ~~La carte apparaît sur l'URL de staging~~ (déployé ; vérification de la carte et du flux : #105) |
| **Semaine 2 — S1** (**en cours**) | Chemin nominal sur fakes : schéma SQL en migrations Alembic, registre des ressources, journal append-only, gateway minimale, moteur d'exécution (plan haché, étapes idempotentes), 3 Skills de départ. Cartes plan et exécution. | S1 vert en CI, cartes visibles |
| ~~**Semaine 3 — S2**~~ | ~~Clarification : l'agent redemande les environnements manquants, questions ouvertes du projet, reprise de la conversation. Carte de clarification.~~ | ~~S2 vert en CI~~ |
| ~~**Semaine 4 — S10**~~ (**terminé**) | Matrice YAML R1 à R10, rôles, niveaux d'autonomie, `approval_required` transmis à l'admin. Carte d'approbation. Authentification de développement avec rôles. | S10 vert en CI |
| **Semaine 5 — S11** | Idempotence de bout en bout : même demande rejouée, aucune ressource en double (contraintes d'unicité, clés d'idempotence). | S11 vert en CI |
| **Semaine 6 — S12** | Approbation sur le hash, plan invalidé si l'état change, expiration. Carte « plan invalidé ». | S12 vert en CI |
| **Essai jetable** | Bootstrap et wrapper Compose sur un conteneur SSH local : exécution, cas d'abus (Compose privilégié, montage hors projet, arguments hostiles), compte rendu dans `docs/spikes/`. | Compte rendu validé, conception ajustée si besoin |
| **Fournisseurs réels** | GitLab : connecteur, sondes, lectures, `create_group`, `create_project`, `set_variable`, `delete_created`. Serveur : bootstrap, wrapper, `server.apply_playbook` (ansible-runner en flux), `inspect`, `healthcheck`. Vercel et DNS selon vos comptes. | S1 réel en staging |
| **Scénarios d'échec** | S3 (playbook en échec), S4 (droit manquant, bouton Continuer), S5 (dérive), S6 (injection de prompt), S7 (secret masqué), S8 (rollback en échec, mode dégradé), S9 (crash du contrôleur). Cartes droit manquant et dérive. | S3 à S9 verts en CI |
| **Évaluation** | S1 à S12 rejoués, 20 exécutions consécutives dont 5 avec échec injecté, mesure du coût et des durées, décision de promotion au niveau 3. | Rapport d'évaluation |

Un décommissionnement (UC15) et les autres cas d'usage hors liste d'étapes sont en v1.1 **(proposition)**.

### Hors PoC

Kubernetes, agent local (sauf blocage SSH), multi-tenance, éditeur de Skills dans l'interface, RAG,
déclenchement par événements, Vault, OPA, Temporal, Backstage.

## v1 (proposition)

Une équipe réelle l'utilise en production, au niveau 3, sur de vrais projets, sans que le propriétaire soit
le goulot. Atteinte quand une équipe a créé un nombre convenu de vrais projets sur une durée convenue, avec
zéro écriture hors registre et chaque exécution reconstituable depuis l'audit.

| Phase | Contenu |
| --- | --- |
| **v1.0 Durcissement** | Modèle de menace écrit, signature des tâches par une clé séparée, secrets dans Vault, liste blanche de registres d'images, wrapper Caddy, accès aux journaux limité, étude de Docker rootless, réconciliation périodique, gardes `check_mode` |
| **v1.1 Produit** | Éditeur de Skills avec revue et test sur demandes simulées, pages Connecteurs et Serveurs, connecteurs GitHub et OVH, authentification OIDC, décommissionnement (UC15), notifications d'approbation, historique et recherche |
| **v1.2 Échelle** | Plusieurs serveurs et hébergeurs, WireGuard ou IP source autorisées, agent local si un hébergeur bloque le SSH, plusieurs équipes isolées, Temporal et OPA seulement si les limites de la table de baux et de la matrice YAML sont atteintes |
| **v1.3 Exploitation** | Observabilité et SLO du contrôleur, sauvegarde et restauration PostgreSQL testées, runbooks, procédure de promotion de niveau (rejeu des évals à chaque changement de modèle, de Skill ou de contrat d'outil), intégration d'une équipe |

Hors v1 sauf décision contraire : Kubernetes, multi-tenance entre organisations, RAG, déclenchement par
événements, Backstage.

## Décisions à prendre

| Avant | Question de la spec | Recommandation |
| --- | --- | --- |
| Semaine 2 | 5. Quel modèle fait tourner l'agent, où sont les logs bruts ? | Modèle Claude derrière `Provider` ; logs bruts en base chiffrée, rétention courte |
| Fournisseurs réels | 1. Convention de nommage GitLab et groupe parent | Exemple réel à fournir |
| Fournisseurs réels | 2. Où vivent les boilerplates | Sous-dépôt GitLab dédié |
| Essai jetable | 3. Wrappers sudo ou Docker rootless | Wrappers sudo au PoC, rootless à étudier en v1.0 |
| Fournisseurs réels | 7. SSH entrant depuis une IP fixe chez tous les hébergeurs ? | Sinon l'agent local entre dans le PoC |
| Scénarios d'échec | 4, 8, 9 : commandes libres par lot, périmètre du niveau 4, champ `purpose` | Conformes aux recommandations de la spec |
| Interface | 6. Les admins voient-ils les logs bruts ? | Non par défaut |

## Prérequis externes

Groupe GitLab de test, serveur de test avec SSH et Docker, compte Vercel et zone DNS de test, exemple réel
de convention de nommage. Ils ne bloquent pas les semaines 1 à 6.

## Risques de planning

- Prérequis externes : repoussés volontairement après les six premières semaines.
- Premier vrai run des workflows : le job de revue des dépendances exige l'activation du graphe de
  dépendances sur le dépôt.
- Mode check d'Ansible : estimation, pas garantie.
- Coût du modèle : mesurable seulement avec le vrai modèle (`evals.yml`).
