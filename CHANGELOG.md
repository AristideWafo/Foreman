# Changelog

## [0.3.0](https://github.com/AristideWafo/Foreman/compare/v0.2.0...v0.3.0) (2026-10-18)


### Features

* add description ([67bc143](https://github.com/AristideWafo/Foreman/commit/67bc143e78e688a2a359dab8defaf40e306f1801))
* **backend:** squelette en couches avec contrats import-linter ([5a4e8ec](https://github.com/AristideWafo/Foreman/commit/5a4e8ec253ee9efb1902393224ca2cc39ab3f425))
* **back:** flux SSE des événements avec reprise ([d83fd14](https://github.com/AristideWafo/Foreman/commit/d83fd146e3a7812b81b7d0144cc9b9ddcc2ce584))
* **back:** flux SSE des événements avec reprise ([#19](https://github.com/AristideWafo/Foreman/issues/19)) ([6808e34](https://github.com/AristideWafo/Foreman/commit/6808e34801af7122012b29b07a0a5dfae79b8531))
* **back:** projets, messages et tour de l'agent en mémoire ([4762901](https://github.com/AristideWafo/Foreman/commit/476290174c4d74149e41b7a6eadadf3fd08219b4))
* **back:** projets, messages et tour de l'agent en mémoire ([#18](https://github.com/AristideWafo/Foreman/issues/18)) ([70bfda9](https://github.com/AristideWafo/Foreman/commit/70bfda9b565ba52a4eac5302e8f0c1e6b1cca82f))
* **contrat:** contrat v1 de l'API et des événements (routes en 501) ([a5cb5fc](https://github.com/AristideWafo/Foreman/commit/a5cb5fcdec45c022d40ecf97c213a0bcab25ee14))
* **contrat:** contrat v1 de l'API et des événements (S1 — P1) ([d902881](https://github.com/AristideWafo/Foreman/commit/d9028817bbc6348f2c23c11a9e0d5f615fd60fbf))
* **deploy:** authentification HTTP (basicAuth Traefik) obligatoire sur env-perso, /healthz public ([76b3fea](https://github.com/AristideWafo/Foreman/commit/76b3fea4c97c7853078ede4541ede8c80f2dc353))
* **deploy:** basicAuth Traefik obligatoire sur env-perso, /healthz public ([#106](https://github.com/AristideWafo/Foreman/issues/106)) ([adac9fb](https://github.com/AristideWafo/Foreman/commit/adac9fbc044625343fef761da2c50021fc6ff731))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([c0f0b53](https://github.com/AristideWafo/Foreman/commit/c0f0b5327dab5ba7c901ed0a06d4de09e6603a94))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([74bd20e](https://github.com/AristideWafo/Foreman/commit/74bd20e38d60a27b30466b1ac616881ef609fb9d))
* **front:** chat, flux d'événements et carte plan ([b28a7bb](https://github.com/AristideWafo/Foreman/commit/b28a7bb08f472471c030cd130a77cf73473e699a))
* **front:** chat, flux d'événements et carte plan ([#20](https://github.com/AristideWafo/Foreman/issues/20)) ([1834548](https://github.com/AristideWafo/Foreman/commit/18345485192fc2fcd84d5b20af61b7c4e2b4012c))
* **frontend:** squelette Vite + React + TS (Tailwind, Vitest, ESLint, Heroicons, Fontsource) ([6a4d7ed](https://github.com/AristideWafo/Foreman/commit/6a4d7ed7bfe941f48e3bf85fe7c20cf6a0f5b174))
* **front:** shadcn (Geist, Heroicons), double sidebar, accueil et conversation ([#114](https://github.com/AristideWafo/Foreman/issues/114)) ([cd1616d](https://github.com/AristideWafo/Foreman/commit/cd1616da87eac01a535a156b2ece52cac610689f))
* version visible et tags release-please compatibles avec le build ([#121](https://github.com/AristideWafo/Foreman/issues/121)) ([6b42853](https://github.com/AristideWafo/Foreman/commit/6b428532ebd6cdad3844ae0a0e4b6e9affa838a2))


### Bug Fixes

* **back:** délai du fournisseur, 404 sur /api inconnu avec la SPA, contrat Last-Event-ID aligné ([c9b7741](https://github.com/AristideWafo/Foreman/commit/c9b774156f889e654e58110f77344368d3bdcf96))
* **back:** plafonds d'abonnés SSE, arrêt borné, Last-Event-ID démesuré (revue indépendante) ([b8cb5d3](https://github.com/AristideWafo/Foreman/commit/b8cb5d32714d8d3cc393ce78c3ee787962753ac2))
* **build:** installer le paquet sans mode éditable dans l'image ([ccc47f4](https://github.com/AristideWafo/Foreman/commit/ccc47f498f0079e196295952f5f556ac7e133cbc))
* **build:** installer le paquet sans mode éditable dans l'image ([8545248](https://github.com/AristideWafo/Foreman/commit/85452489bef872d5be129eb56f3f1c87f3f0fdd3))
* **ci:** nom d'image GHCR en minuscules ([7ae49e2](https://github.com/AristideWafo/Foreman/commit/7ae49e2b271ce1a3bf1bbf527a8c5c9ec79017e8))
* **ci:** nom d'image GHCR en minuscules dans Build et Deploy ([0fc5fc9](https://github.com/AristideWafo/Foreman/commit/0fc5fc9f723fca756405cedaf998af0dc5ae032c))
* **ci:** port SSH configurable pour le déploiement ([1411db8](https://github.com/AristideWafo/Foreman/commit/1411db8625d5f093b1ddb406043917d7ce24b96f))
* **ci:** port SSH configurable pour le déploiement ([41976c7](https://github.com/AristideWafo/Foreman/commit/41976c7bdfc607e36fb62722631ce0c90d265e0f))
* **contrat:** corrections de la revue indépendante avant gel ([19636d8](https://github.com/AristideWafo/Foreman/commit/19636d8599ca545ad96779aac3795d9fdc6649b5))
* **contrat:** descriptions d'erreurs explicites (openapi.json identique en Python 3.12 et 3.13) ([00cc359](https://github.com/AristideWafo/Foreman/commit/00cc35930c0c8bdc942963a4f69de3f4e6ac2748))
* évals sans scénario encore, cible de vérification des intégrations ([c189302](https://github.com/AristideWafo/Foreman/commit/c1893022b728261c7fc16a47f2827dde1c1d7ee6))
* **front:** corrections de la revue indépendante (v, formes inattendues, 422, tests du réducteur) ([ebc1cf7](https://github.com/AristideWafo/Foreman/commit/ebc1cf7b1f5f386adc397554181ba18a212bba46))
* **front:** les étapes d'une carte sont numérotées à partir de 1 (contrat v1) ([0eb1914](https://github.com/AristideWafo/Foreman/commit/0eb191455148d9244ef4294466f2c0f842436b49))

## [0.2.0](https://github.com/AristideWafo/Foreman/compare/foreman-v0.1.0...foreman-v0.2.0) (2026-10-18)


### Features

* add description ([67bc143](https://github.com/AristideWafo/Foreman/commit/67bc143e78e688a2a359dab8defaf40e306f1801))
* **backend:** squelette en couches avec contrats import-linter ([5a4e8ec](https://github.com/AristideWafo/Foreman/commit/5a4e8ec253ee9efb1902393224ca2cc39ab3f425))
* **back:** flux SSE des événements avec reprise ([d83fd14](https://github.com/AristideWafo/Foreman/commit/d83fd146e3a7812b81b7d0144cc9b9ddcc2ce584))
* **back:** flux SSE des événements avec reprise ([#19](https://github.com/AristideWafo/Foreman/issues/19)) ([6808e34](https://github.com/AristideWafo/Foreman/commit/6808e34801af7122012b29b07a0a5dfae79b8531))
* **back:** projets, messages et tour de l'agent en mémoire ([4762901](https://github.com/AristideWafo/Foreman/commit/476290174c4d74149e41b7a6eadadf3fd08219b4))
* **back:** projets, messages et tour de l'agent en mémoire ([#18](https://github.com/AristideWafo/Foreman/issues/18)) ([70bfda9](https://github.com/AristideWafo/Foreman/commit/70bfda9b565ba52a4eac5302e8f0c1e6b1cca82f))
* **contrat:** contrat v1 de l'API et des événements (routes en 501) ([a5cb5fc](https://github.com/AristideWafo/Foreman/commit/a5cb5fcdec45c022d40ecf97c213a0bcab25ee14))
* **contrat:** contrat v1 de l'API et des événements (S1 — P1) ([d902881](https://github.com/AristideWafo/Foreman/commit/d9028817bbc6348f2c23c11a9e0d5f615fd60fbf))
* **deploy:** authentification HTTP (basicAuth Traefik) obligatoire sur env-perso, /healthz public ([76b3fea](https://github.com/AristideWafo/Foreman/commit/76b3fea4c97c7853078ede4541ede8c80f2dc353))
* **deploy:** basicAuth Traefik obligatoire sur env-perso, /healthz public ([#106](https://github.com/AristideWafo/Foreman/issues/106)) ([adac9fb](https://github.com/AristideWafo/Foreman/commit/adac9fbc044625343fef761da2c50021fc6ff731))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([c0f0b53](https://github.com/AristideWafo/Foreman/commit/c0f0b5327dab5ba7c901ed0a06d4de09e6603a94))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([74bd20e](https://github.com/AristideWafo/Foreman/commit/74bd20e38d60a27b30466b1ac616881ef609fb9d))
* **front:** chat, flux d'événements et carte plan ([b28a7bb](https://github.com/AristideWafo/Foreman/commit/b28a7bb08f472471c030cd130a77cf73473e699a))
* **front:** chat, flux d'événements et carte plan ([#20](https://github.com/AristideWafo/Foreman/issues/20)) ([1834548](https://github.com/AristideWafo/Foreman/commit/18345485192fc2fcd84d5b20af61b7c4e2b4012c))
* **frontend:** squelette Vite + React + TS (Tailwind, Vitest, ESLint, Heroicons, Fontsource) ([6a4d7ed](https://github.com/AristideWafo/Foreman/commit/6a4d7ed7bfe941f48e3bf85fe7c20cf6a0f5b174))
* **front:** shadcn (Geist, Heroicons), double sidebar, accueil et conversation ([#114](https://github.com/AristideWafo/Foreman/issues/114)) ([cd1616d](https://github.com/AristideWafo/Foreman/commit/cd1616da87eac01a535a156b2ece52cac610689f))


### Bug Fixes

* **back:** délai du fournisseur, 404 sur /api inconnu avec la SPA, contrat Last-Event-ID aligné ([c9b7741](https://github.com/AristideWafo/Foreman/commit/c9b774156f889e654e58110f77344368d3bdcf96))
* **back:** plafonds d'abonnés SSE, arrêt borné, Last-Event-ID démesuré (revue indépendante) ([b8cb5d3](https://github.com/AristideWafo/Foreman/commit/b8cb5d32714d8d3cc393ce78c3ee787962753ac2))
* **build:** installer le paquet sans mode éditable dans l'image ([ccc47f4](https://github.com/AristideWafo/Foreman/commit/ccc47f498f0079e196295952f5f556ac7e133cbc))
* **build:** installer le paquet sans mode éditable dans l'image ([8545248](https://github.com/AristideWafo/Foreman/commit/85452489bef872d5be129eb56f3f1c87f3f0fdd3))
* **ci:** nom d'image GHCR en minuscules ([7ae49e2](https://github.com/AristideWafo/Foreman/commit/7ae49e2b271ce1a3bf1bbf527a8c5c9ec79017e8))
* **ci:** nom d'image GHCR en minuscules dans Build et Deploy ([0fc5fc9](https://github.com/AristideWafo/Foreman/commit/0fc5fc9f723fca756405cedaf998af0dc5ae032c))
* **ci:** port SSH configurable pour le déploiement ([1411db8](https://github.com/AristideWafo/Foreman/commit/1411db8625d5f093b1ddb406043917d7ce24b96f))
* **ci:** port SSH configurable pour le déploiement ([41976c7](https://github.com/AristideWafo/Foreman/commit/41976c7bdfc607e36fb62722631ce0c90d265e0f))
* **contrat:** corrections de la revue indépendante avant gel ([19636d8](https://github.com/AristideWafo/Foreman/commit/19636d8599ca545ad96779aac3795d9fdc6649b5))
* **contrat:** descriptions d'erreurs explicites (openapi.json identique en Python 3.12 et 3.13) ([00cc359](https://github.com/AristideWafo/Foreman/commit/00cc35930c0c8bdc942963a4f69de3f4e6ac2748))
* évals sans scénario encore, cible de vérification des intégrations ([c189302](https://github.com/AristideWafo/Foreman/commit/c1893022b728261c7fc16a47f2827dde1c1d7ee6))
* **front:** corrections de la revue indépendante (v, formes inattendues, 422, tests du réducteur) ([ebc1cf7](https://github.com/AristideWafo/Foreman/commit/ebc1cf7b1f5f386adc397554181ba18a212bba46))
* **front:** les étapes d'une carte sont numérotées à partir de 1 (contrat v1) ([0eb1914](https://github.com/AristideWafo/Foreman/commit/0eb191455148d9244ef4294466f2c0f842436b49))
