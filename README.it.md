<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

# prism-verify

Servizio di verifica in tempo reale per i flussi di lavoro degli agenti. Verifica multi-lente, con famiglie diverse e senza ragionamento, con ricevute riproducibili. **[Pagina di destinazione e manuale →](https://mcp-tool-shop-org.github.io/prism-verify/)**

## Installazione

Installa l'interfaccia a riga di comando `prism` (e il servizio HTTP) nel tuo PATH:

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Nessun Python? Utilizza il launcher npm (scarica e verifica SHA256 di un binario precompilato):

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

Oppure aggiungilo come libreria: `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`:

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Avvio rapido

Prism esegue sempre la verifica con una famiglia di modelli **diversa** da quella del chiamante (Blocco 1), quindi
configura almeno un provider con una famiglia di modelli alternativa. Imposta una chiave di firma (o `PRISM_DEV=1`
per l'uso locale) in modo che le ricevute possano essere scritte:

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## Architettura

Prism applica quattro blocchi architetturali al contratto API:

1. **Famiglia diversa:** la famiglia di modelli del chiamante è sempre esclusa dalla verifica.
2. **Senza ragionamento:** il CoT del produttore viene rimosso prima di attraversare il confine della famiglia.
3. **Multi-lente:** almeno 3 lenti indipendenti vengono eseguite in parallelo.
4. **Consapevole della submodularità:** rifiuta se le lenti sono troppo d'accordo (segnale collassato).

## Servizio HTTP

Esegui Prism come servizio HTTP (richiede l'extra `[http]`):

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| Endpoint | Cosa fa |
|---|---|
| `POST /verify` | Verifica un artefatto (stesso contratto dell'interfaccia a riga di comando). Opera entro il budget; `Prefer: respond-async` + un URL `webhook` → `202`, il risultato viene inviato al webhook (firmato). |
| `GET /replay/{receipt_id}` | La ricevuta firmata + `signature_valid`. |
| `POST /verify-receipt` | Verifica una ricevuta autonoma (tra diversi strumenti). |
| `GET /healthz` | Funzionamento + famiglie di verificatori configurate (nessuna autenticazione). |

Imposta le chiavi API (memorizzate in forma hash) — Prism è impostato per essere **sicuro per impostazione predefinita**, quindi `/verify` viene rifiutato finché le chiavi
non sono configurate o non si sceglie di utilizzare l'autenticazione locale:

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

Gli errori sono in formato RFC 9457 `application/problem+json`; `POST /verify` rispetta un'intestazione `Idempotency-Key`
e un limite di frequenza per chiave (`429` + `Retry-After`). I webhook asincroni/di escalation sono
Standard-Webhooks-signed, protetti contro SSRF (nessun target interno/di metadati), vengono ritentati e contengono un
compensatore di eventi di annullamento denominato.

## Ricevute e firma (Ed25519, verificabile da chiunque)

Ogni verifica produce una ricevuta firmata e riproducibile in `~/.prism/receipts.db`. La versione 0.4 firma
le nuove ricevute con **Ed25519 (RFC 8032)** per impostazione predefinita, quindi **uno strumento diverso può verificare una ricevuta di Prism con la chiave pubblica di Prism — nessuna chiave segreta condivisa**:

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

La firma copre il risultato, gli hash dell'artefatto pre/post-rimozione, il modello di verifica, la
matrice di submodularità, gli hash dei prompt per lente (riproducibili byte per byte), gli indicatori di recupero delle citazioni e l'algoritmo/l'ID della chiave di firma. Le ricevute **HMAC** legacy continuano a essere verificate (imposta
`PRISM_SIGNING_SECRET`); `PRISM_DEV=1` crea una chiave di sviluppo per l'uso locale. Prism **rifiuta di avviarsi**
se non è configurata alcuna chiave, piuttosto che firmare silenziosamente con una chiave pubblicamente nota.

Gestisci le ricevute memorizzate con i comandi del compensatore:

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Sicurezza e privacy

- **Modello di minaccia.** Prism legge l'artefatto + l'intento che gli passi e le risposte dei modelli di verifica,
e scrive le ricevute firmate in un database SQLite locale. **Non** legge
la tua directory di origine, l'ambiente o le credenziali oltre alle chiavi API del provider che fornisci tramite
le variabili d'ambiente. Le firme delle ricevute offrono **verificabilità da parte di terzi** (Ed25519: un
consumatore verifica con la chiave pubblica, nessuna chiave segreta condivisa), ma non sono a prova di manomissione contro un
attaccante locale con accesso alla chiave privata memorizzata su disco — questo è lo stesso limite della chiave segreta HMAC. Per una vera resistenza alla manomissione, conserva la chiave in un HSM e ancora le ricevute in un
registro di trasparenza (il percorso di hardening specificato).
- **Superficie HTTP.** `prism serve` si lega all'indirizzo loopback per impostazione predefinita, è impostato per essere **sicuro per impostazione predefinita** (nessun `/verify`
senza chiavi API), memorizza le chiavi in forma hash e **protegge contro SSRF** gli URL webhook forniti dal chiamante
(nessun target interno/locale/di metadati). Esegue gli artefatti forniti dal chiamante attraverso un modello;
un artefatto può *tentare* l'iniezione di prompt, ma non può modificare lo schema del risultato o esfiltrare
le chiavi del provider di Prism.
- **Nessun telemetria.** Prism invia richieste solo ai provider di modelli che configuri
(Anthropic / OpenAI / Google / Ollama locale). Nient'altro.
- Politica completa: [SECURITY.md](SECURITY.md).

## Licenza

MIT
