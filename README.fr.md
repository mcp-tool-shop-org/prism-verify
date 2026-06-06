<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="500">
</p>

<p align="center">
  <a href="https://pypi.org/project/prism-verify/"><img src="https://img.shields.io/pypi/v/prism-verify" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/prism-verify"><img src="https://img.shields.io/npm/v/@mcptoolshop/prism-verify" alt="npm"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/"><img src="https://img.shields.io/badge/Landing_Page-live-22d3ee" alt="Landing Page"></a>
  <a href="https://mcp-tool-shop-org.github.io/prism-verify/handbook/"><img src="https://img.shields.io/badge/Handbook-docs-22d3ee" alt="Handbook"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
</p>

# 

Service d’évaluation en temps réel pour les flux de travail des agents. Vérification à plusieurs niveaux, avec des familles différentes, sans raisonnement explicite et avec des reçus rejouables. **[Page d’accueil et manuel →](https://mcp-tool-shop-org.github.io/prism-verify/)**

## Installation

Installez l’interface en ligne de commande `prism` (et le service HTTP) dans votre PATH :

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Pas de Python ? Utilisez le lanceur npm (télécharge et vérifie avec SHA256 un binaire précompilé) :

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

Ou ajoutez-le en tant que bibliothèque : options supplémentaires : `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]` :

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Démarrage rapide

Prism vérifie toujours avec une famille de modèles **différente** de celle de l’appelant (Lock 1), donc configurez au moins un fournisseur de famille de modèles alternatif. Générez une clé de signature Ed25519 (la valeur par défaut : les reçus sont vérifiables par toute personne disposant de la clé publique) afin que les reçus puissent être écrits, ou utilisez `PRISM_DEV=1` pour une utilisation locale :

```bash
prism keygen --out ~/.prism/signing_key.pem      # Ed25519 keypair (default signing)
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem # or: export PRISM_DEV=1 (local play)
export ANTHROPIC_API_KEY="sk-ant-..."             # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

> Alternative ancienne : `export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"` signe les reçus avec HMAC (vérifiables uniquement par les détenteurs de ce secret partagé — voir [Reçus](#receipts--signing-ed25519-verifiable-by-anyone)).

## Architecture

Prism applique quatre contraintes architecturales au niveau du contrat d’API :

1. **Famille différente** : la famille de modèles de l’appelant est toujours exclue de la vérification.
2. **Suppression du raisonnement** : le CoT du producteur est supprimé avant de franchir la limite de la famille.
3. **Multi-niveaux** : au moins 3 niveaux indépendants fonctionnent en parallèle.
4. **Connaissance de la sous-modularité** : refuse si les niveaux sont trop d’accord (signal affaibli).

Pour les artefacts de **citation**, un niveau de vérification est appliqué avant l’analyse de la pertinence du LLM : chaque étape déterministe rejette ce qu’elle peut *prouver*, sinon elle s’abstient :

- **Niveau de vérification de l’existence** : récupération en direct à partir d’arXiv/Crossref ; un identifiant fabriqué est rejeté, et non analysé.
- **Niveau de vérification numérique/unitaire** : une permutation de pourcentage, une erreur d’échelle unitaire (42 milli- par rapport à micro-arcsecondes), ou une fausseté de direction de comparaison (5,0 < 5,8 ≠ « dépassé ») sont détectées arithmétiquement.
- **Analyse de la pertinence** : vérification par la famille de modèles différente, sans raisonnement, par rapport au résumé récupéré.
- **Niveau de vérification NLI orthogonal** *(facultatif, `PRISM_NLI_FLOOR`)* : un encodeur NLI croisé rejette une affirmation que le LLM a donnée, mais qu’un modèle mécaniquement différent ne confirme pas.

### Utilisez votre propre outil de vérification

L’outil d’analyse peut être utilisé avec un modèle que **vous hébergez** au lieu d’une API hébergée. Pour ce faire, activez l’option via `PRISM_LOCAL_VERIFIER_ENDPOINT`. Cette option est différente selon la famille et permet une ouverture par défaut vers vos outils de vérification hébergés. La vérification la plus fréquente est gratuite et vos données restent locales. Un collecteur d’informations optionnel (`PRISM_HARVEST_PATH`) enregistre les triplets `(revendication, preuve, verdict)`, ce qui vous permet de les utiliser pour l’apprentissage. Consultez le [manuel](https://mcp-tool-shop-org.github.io/prism-verify/handbook/local-verifier/).

## Calibration et évaluation comparative (`prism eval`)

Prism est conçu pour être **mesuré**, et non pas seulement pour faire des affirmations. `prism eval` exécute les analyses sur un corpus étiqueté et génère un rapport : sur les propres données de Prism, il indique la précision/le rappel/le MCC par analyse, la matrice de diversité inter-analyses (alpha de Krippendorff + kappa de Cohen par paires), le gain de couverture sous-modulaire, la précision de la décision et l’étalonnage de la confiance (ECE/Brier), le tout avec un intervalle de confiance honnête.

```bash
prism eval --split public --runs 3     # measure against the bundled corpus (needs a verifier)
prism eval --offline                    # deterministic mock (CI smoke; NOT a real measurement)
```

Consultez le [manuel d’évaluation](https://mcp-tool-shop-org.github.io/prism-verify/handbook/evaluation/) pour connaître la méthode et un exemple concret.

## Service HTTP

Exécutez Prism en tant que service HTTP (nécessite l’option supplémentaire `[http]` ):

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| Point de terminaison | Fonctionnement |
|---|---|
| `POST /verify` | Vérifie un artefact (même contrat que l’interface en ligne de commande). Bloque dans les limites du budget ; `Prefer: respond-async` + une URL `webhook` → `202`, le résultat est transmis au webhook (signé). |
| `GET /replay/{receipt_id}` | Le reçu signé + `signature_valid`. |
| `POST /verify-receipt` | Vérifie un reçu autonome (entre différents outils). |
| `GET /healthz` | Vérifie la disponibilité + les familles de vérificateurs configurées (sans authentification). |

Définissez les clés d’API (hachées au repos) : Prism est **par défaut en mode sécurisé**, de sorte que `/verify` est refusé jusqu’à ce que les clés soient configurées ou que vous choisissiez de ne pas utiliser d’authentification locale :

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

Les erreurs sont au format RFC 9457 `application/problem+json` ; `POST /verify` prend en charge un en-tête `Idempotency-Key` et une limite de débit par clé (`429` + `Retry-After`). Les webhooks asynchrones/d’escalade sont signés selon la norme Standard-Webhooks, protégés contre le SSRF (aucune cible interne/métadonnée), sont réessayés et contiennent un compensateur d’événement d’annulation nommé.

## Reçus et signature (Ed25519, vérifiable par n’importe qui)

Chaque vérification produit un reçu signé et rejouable dans `~/.prism/receipts.db`. La version 0.4 signe les nouveaux reçus avec **Ed25519 (RFC 8032)** par défaut, de sorte qu’un **outil différent peut vérifier un reçu Prism avec la clé publique de Prism : aucune clé secrète partagée** :

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

La signature couvre le résultat, les hachages des artefacts pré/post-suppression, le modèle de vérification, la matrice de sous-modularité, les hachages des invites par niveau (rejouables octet par octet), les références de récupération et l’algorithme/l’identifiant de signature (`alg`/`kid`). Les anciens reçus **HMAC** sont toujours valides (définissez `PRISM_SIGNING_SECRET`) ; `PRISM_DEV=1` crée une clé de développement pour une utilisation locale. Prism **refuse de démarrer** les chemins de vérification/relecture/service/MCP si aucune clé n’est configurée, plutôt que de signer silencieusement avec une clé connue publiquement.

Gérez les reçus stockés à l’aide des commandes du compensateur :

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Sécurité et confidentialité

- **Modèle de menace.** Prism lit l’artefact + l’intention que vous transmettez et les réponses des modèles de vérification, et écrit des reçus signés dans une base de données SQLite locale. Il **ne** lit **pas** votre arborescence de code source, votre environnement ou vos informations d’identification, au-delà des clés d’API des fournisseurs que vous fournissez via les variables d’environnement. Les signatures des reçus offrent une **vérifiabilité par un tiers** (Ed25519 : un consommateur vérifie avec la clé publique, aucune clé secrète partagée), mais ne sont pas inviolables contre un attaquant disposant d’un accès root local qui peut lire la clé privée stockée sur le disque : c’est le même niveau de sécurité que la clé secrète HMAC. Pour une véritable résistance à la falsification, conservez la clé dans un HSM et ancrez les reçus dans un journal de transparence (le chemin d’amélioration spécifié).
- **Surface HTTP.** `prism serve` se lie par défaut à l’adresse de bouclage, est **par défaut en mode sécurisé** (pas de `/verify` sans clés d’API), hache les clés au repos et **protège contre le SSRF** les URL de webhook fournies par l’appelant (aucune cible interne/locale/métadonnée). Il exécute les artefacts fournis par l’appelant dans un modèle ; un artefact peut *tenter* une injection d’invite, mais ne peut pas modifier le schéma du résultat ou exfiltrer les clés des fournisseurs de Prism.
- **Pas de télémétrie.** Prism envoie des requêtes uniquement aux fournisseurs de modèles que vous configurez (Anthropic / OpenAI / Google / Ollama local). Rien d’autre.
- Politique complète : [SECURITY.md](SECURITY.md).

## Licence

Licence MIT
