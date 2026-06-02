<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="320">
</p>

# prism-verify

Service d’évaluation en temps réel pour les flux de travail des agents. Vérification à plusieurs niveaux, avec des familles différentes, sans raisonnement, et avec des reçus rejouables.

## Installer

Installez l’interface en ligne de commande `prism` (et le service HTTP) dans votre PATH :

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Pas de Python ? Utilisez le lanceur npm (télécharge et vérifie avec SHA256 un binaire précompilé) :

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

Ou ajoutez-le comme bibliothèque : options supplémentaires : `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]` :

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Démarrage rapide

Prism effectue toujours une vérification avec une famille de modèles **différente** de celle de l’appelant (verrou 1). Configurez donc au moins un fournisseur de famille alternative. Définissez une clé de signature (ou `PRISM_DEV=1` pour une utilisation locale) afin que les reçus puissent être écrits :

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## Architecture

Prism applique quatre contraintes architecturales au niveau du contrat d’API :

1. **Famille différente** : la famille de modèles de l’appelant est toujours exclue de la vérification.
2. **Suppression du raisonnement** : le CoT du producteur est supprimé avant de franchir la limite de la famille.
3. **Multi-niveaux** : au moins 3 niveaux indépendants fonctionnent en parallèle.
4. **Connaissance de la sous-modularité** : refuse si les niveaux sont trop d’accord (signal affaibli).

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

Les erreurs sont au format RFC 9457 `application/problem+json` ; `POST /verify` prend en charge un en-tête `Idempotency-Key` et une limite de débit par clé (`429` + `Retry-After`). Les webhooks asynchrones/d’escalade sont signés selon la norme Standard-Webhooks, protégés contre le SSRF (pas de cibles internes/métadonnées), sont réessayés et contiennent un compensateur d’événement d’annulation nommé.

## Reçus et signature (Ed25519, vérifiable par n’importe qui)

Chaque vérification produit un reçu signé et rejouable dans `~/.prism/receipts.db`. La version 0.4 signe par défaut les nouveaux reçus avec **Ed25519 (RFC 8032)**, de sorte qu’un **outil différent peut vérifier un reçu Prism avec la clé publique de Prism : pas de clé secrète partagée** :

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

La signature couvre le résultat, les hachages des artefacts pré/post-suppression, le modèle de vérification, la matrice de sous-modularité, les hachages des invites par niveau (rejouables octet par octet), les références de récupération des citations et l’algorithme/l’identifiant de signature (`alg`/`kid`). Les anciens reçus **HMAC** sont toujours valides (définissez `PRISM_SIGNING_SECRET`) ; `PRISM_DEV=1` crée une clé de développement pour une utilisation locale. Prism **refuse de démarrer** les chemins de vérification/relecture/service/MCP si aucune clé n’est configurée, plutôt que de signer silencieusement avec une clé connue publiquement.

Gérez les reçus stockés à l’aide des commandes du compensateur :

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Sécurité et confidentialité

- **Modèle de menace.** Prism lit l’artefact + l’intention que vous transmettez et les réponses des modèles de vérification, et écrit des reçus signés dans une base de données SQLite locale. Il ne lit **pas** votre arborescence de code source, votre environnement ou vos informations d’identification, à l’exception des clés d’API des fournisseurs que vous fournissez via les variables d’environnement. Les signatures des reçus offrent une **vérifiabilité par un tiers** (Ed25519 : un consommateur vérifie avec la clé publique, pas de clé secrète partagée), mais ne sont pas inviolables contre un attaquant disposant d’un accès root local qui peut lire la clé privée stockée sur le disque : c’est le même niveau de sécurité que la clé secrète HMAC. Pour une véritable résistance à la falsification, stockez la clé dans un HSM et ancrez les reçus dans un journal de transparence (le chemin d’amélioration spécifié).
- **Surface HTTP.** `prism serve` se lie par défaut à l’adresse de bouclage, est **par défaut en mode sécurisé** (pas de `/verify` sans clés d’API), hache les clés au repos et **protège contre le SSRF** les URL de webhook fournies par l’appelant (pas de cibles internes/locales/métadonnées). Il exécute les artefacts fournis par l’appelant dans un modèle ; un artefact peut *tenter* une injection d’invite, mais ne peut pas modifier le schéma du résultat ou extraire les clés des fournisseurs de Prism.
- **Pas de télémétrie.** Prism envoie des requêtes uniquement aux fournisseurs de modèles que vous configurez (Anthropic / OpenAI / Google / Ollama local). Rien d’autre.
- Politique complète : [SECURITY.md](SECURITY.md).

## Licence

MIT
