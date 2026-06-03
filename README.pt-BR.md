<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
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

Serviço de avaliação em tempo real para fluxos de trabalho de agentes. Verificação com múltiplas perspectivas, que considera as diferenças entre famílias, elimina o raciocínio complexo e permite a reprodução dos resultados. **[Página inicial e manual →](https://mcp-tool-shop-org.github.io/prism-verify/)**

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

O Prism sempre verifica com um modelo de família **diferente** do modelo que fez a chamada (Lock 1), portanto,
configure pelo menos um provedor de família alternativo. Gere uma chave de assinatura Ed25519 (o padrão —
os recibos podem ser verificados por qualquer pessoa que tenha a chave pública) para que os recibos possam ser gerados, ou use
`PRISM_DEV=1` para testes locais:

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

> Alternativa legada: `export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"` assina os recibos com
> HMAC (verificáveis apenas pelos detentores desse segredo compartilhado — veja [Recibos](#receipts--signing-ed25519-verifiable-by-anyone)).

## Arquitetura

O Prism aplica quatro restrições arquiteturais no contrato da API:

1. **Família diferente** — a família de modelos do chamador é sempre excluída da verificação.
2. **Sem raciocínio** — o CoT do produtor é removido antes de atravessar a fronteira da família.
3. **Múltiplas lentes** — pelo menos 3 lentes independentes são executadas em paralelo.
4. **Consciência da submodularidade** — recusa se as lentes concordarem demais (sinal colapsado).

Para os artefatos de **citação**, uma camada de verificação é aplicada antes da análise da consistência do LLM — cada etapa determinística rejeita o que pode *comprovar*, caso contrário, abstém-se:

- **Camada de existência** — recuperação em tempo real do arXiv/Crossref; um identificador fabricado é descartado, sem que se faça qualquer análise sobre ele.
- **Camada numérica/de unidades** — uma troca de percentagens, um erro na escala de unidades (42 mili- versus micro-segundos de arco) ou uma falsidade na direção da comparação (5,0 < 5,8 ≠ "excedido) são detectados aritmeticamente.
- **Análise de consistência** — verificação do LLM, que difere em termos de família e que não utiliza raciocínio, em relação ao resumo recuperado.
- **Camada NLI ortogonal** *(opcional, `PRISM_NLI_FLOOR`)* — um codificador NLI (Inferência de Linguagem Natural) rejeita uma afirmação "confirmada" pelo LLM, mas que um modelo mecanicamente diferente não corrobora.

## Calibração e teste de desempenho (`prism eval`)

O Prism foi desenvolvido para ser **mensurado**, e não apenas para fazer afirmações. O comando `prism eval` executa as lentes em um corpus rotulado e gera relatórios — com base nos próprios dados do Prism — sobre a precisão/revocação/MCC por lente, a matriz de diversidade inter-lente (alfa de Krippendorff + kappa de Cohen por pares), o ganho de cobertura submodular, a precisão do veredicto e a calibração da confiança (ECE/Brier), cada um com um intervalo de confiança honesto.

```bash
prism eval --split public --runs 3     # measure against the bundled corpus (needs a verifier)
prism eval --offline                    # deterministic mock (CI smoke; NOT a real measurement)
```

A execução da versão 0.5 (localmente, `mistral-small:24b`) revelou uma lacuna real em um bloqueio central: a métrica de submodularidade em tempo de execução (Jaccard do conjunto de resultados, ρ) apresenta o valor **0,0 para cada par de lentes**, enquanto o kappa de Cohen no nível de decisão é de **0,73–0,81** — o limite `ρ ≤ 0,25` é *cego à correlação das lentes que o kappa revela*. Descobrir isso é o objetivo principal da análise; os resultados completos e o método estão em
[`eval/RESULTS.md`](eval/RESULTS.md) e [`design/07`](design/07-slice1-calibration.md).

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
