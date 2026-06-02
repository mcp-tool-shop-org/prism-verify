<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="320">
</p>

# prism-verify

Serviço de avaliação em tempo de execução para fluxos de trabalho de agentes. Verificação com múltiplas lentes, com famílias diferentes, sem raciocínio e com recibos reproduzíveis.

## Instalar

Instale a CLI `prism` (e o serviço HTTP) no seu PATH:

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

Sem Python? Use o iniciador npm (faz o download e verifica o SHA256 de um binário pré-compilado):

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

Ou adicione-o como uma biblioteca — extras: `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`:

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Início rápido

O Prism sempre verifica com uma família de modelos **diferente** da do chamador (Bloqueio 1), portanto,
configure pelo menos um provedor de família alternativa. Defina uma chave de assinatura (ou `PRISM_DEV=1`
para testes locais) para que os recibos possam ser gravados:

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## Arquitetura

O Prism aplica quatro restrições arquiteturais no contrato da API:

1. **Família diferente** — a família de modelos do chamador é sempre excluída da verificação.
2. **Sem raciocínio** — o CoT do produtor é removido antes de atravessar a fronteira da família.
3. **Múltiplas lentes** — pelo menos 3 lentes independentes são executadas em paralelo.
4. **Consciência da submodularidade** — recusa se as lentes concordarem demais (sinal colapsado).

## Serviço HTTP

Execute o Prism como um serviço HTTP (requer o extra `[http]`):

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| Ponto de extremidade | O que ele faz |
|---|---|
| `POST /verify` | Verifica um artefato (mesmo contrato da CLI). Bloqueia dentro do orçamento; `Prefer: respond-async` + uma URL de `webhook` → `202`, o resultado é entregue ao webhook (assinado). |
| `GET /replay/{receipt_id}` | O recibo assinado + `signature_valid`. |
| `POST /verify-receipt` | Verifica um recibo independente (entre ferramentas). |
| `GET /healthz` | Disponibilidade + famílias de verificadores configuradas (sem autenticação). |

Defina as chaves da API (armazenadas de forma criptografada) — o Prism é **fail-closed**, portanto, `/verify` é recusado até que as chaves
sejam configuradas ou você opte por não usar a autenticação local:

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

Os erros são RFC 9457 `application/problem+json`; `POST /verify` honra um cabeçalho `Idempotency-Key`
e um limite de taxa por chave (`429` + `Retry-After`). Webhooks assíncronos/de escalonamento são
Standard-Webhooks-signed, protegidos contra SSRF (sem destinos internos/de metadados), são repetidos e contêm um
compensador de evento de cancelamento nomeado.

## Recibos e assinatura (Ed25519, verificável por qualquer pessoa)

Cada verificação produz um recibo assinado e reproduzível em `~/.prism/receipts.db`. A versão 0.4 assina
novos recibos com **Ed25519 (RFC 8032)** por padrão, portanto, **uma ferramenta diferente pode verificar um recibo do Prism com a chave pública do Prism — sem chave secreta compartilhada**:

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

A assinatura cobre o resultado, os hashes do artefato pré/pós-remoção, o modelo do verificador, a
matriz de submodularidade, os hashes dos prompts por lente (reproduzíveis byte a byte), os pinos de recuperação de citações e o `alg`/`kid` de assinatura. Os recibos **HMAC** legados ainda são verificados (defina
`PRISM_SIGNING_SECRET`); `PRISM_DEV=1` gera uma chave de desenvolvimento para testes locais. O Prism **se recusa a iniciar**
os caminhos de verificação/reprodução/serviço/MCP se nenhuma chave for configurada, em vez de assinar silenciosamente
com uma chave publicamente conhecida.

Gerencie os recibos armazenados com os comandos do compensador:

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Segurança e privacidade

- **Modelo de ameaças.** O Prism lê o artefato + a intenção que você passa e as respostas dos modelos de verificador, e grava recibos assinados em um banco de dados SQLite local. Ele **não** lê sua
árvore de código-fonte, ambiente ou credenciais além das chaves da API do provedor que você fornece por meio de
variáveis de ambiente. As assinaturas dos recibos fornecem **verificabilidade de terceiros** (Ed25519: um
consumidor verifica com a chave pública, sem chave secreta compartilhada), mas não são à prova de adulteração contra um
atacante com acesso root local que pode ler a chave privada armazenada em disco — esse é o mesmo limite da chave secreta HMAC. Para uma resistência genuína à adulteração, armazene a chave em um HSM e ancore os recibos em um
registro de transparência (o caminho de endurecimento nomeado).
- **Superfície HTTP.** `prism serve` se vincula ao loopback por padrão, é **fail-closed** (sem `/verify`
sem chaves de API), armazena as chaves de forma criptografada e **protege contra SSRF** as URLs do webhook fornecidas pelo chamador
(sem destinos internos/de link local/de metadados). Ele executa os artefatos fornecidos pelo chamador por meio de um modelo;
um artefato pode *tentar* injeção de prompt, mas não pode alterar o esquema de resultado ou exfiltrar
as chaves do provedor do Prism.
- **Sem telemetria.** O Prism envia solicitações apenas aos provedores de modelo que você configura
(Anthropic / OpenAI / Google / Ollama local). Nada mais.
- Política completa: [SECURITY.md](SECURITY.md).

## Licença

MIT
