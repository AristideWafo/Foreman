---
name: docker-staging-deploy
version: 1
status: draft
description: Préparer le serveur de staging, déployer le projet avec Docker Compose et vérifier sa santé.
tools: [server.apply_playbook, server.healthcheck, dns.list_records]
---

# Objectif
Mettre un projet en ligne sur le staging avec Docker Compose, derrière le wildcard DNS de l'équipe.

# Instructions
0. Si l'environnement ou la stack manquent (`referentiels/project-schema.yaml`), appeler `ask_user`
   avant tout plan : ne jamais les deviner, ne proposer aucun plan tant que la réponse manque.
1. Lire `referentiels/infra-staging.yaml` : serveur, répertoire du projet, fichier Compose.
2. Vérifier avec `dns.list_records` que le wildcard du staging existe ; ne jamais créer d'enregistrement
   DNS en staging, le wildcard est géré en externe.
3. Planifier `server.apply_playbook` avec `bootstrap_project`, puis avec `deploy_compose`.
4. Terminer par `server.healthcheck` et rapporter son résultat tel quel.
5. Présenter le plan au développeur avant toute exécution.

# Règles
- Ne jamais exécuter de commande libre sur le serveur : seuls les playbooks de la liste fermée existent.
- Ne jamais afficher ni demander la valeur d'un secret ; les valeurs viennent du gestionnaire de secrets.
- Ne jamais cibler un autre environnement que celui du plan.
- Un health check en échec n'est jamais présenté comme un succès.

# Résultat attendu
URL du projet en staging, statut de chaque étape, résultat du health check.
