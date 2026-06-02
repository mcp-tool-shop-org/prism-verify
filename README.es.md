<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify logo" width="320">
</p>

# prism-verify

Servicio de validación en tiempo de ejecución para flujos de trabajo de agentes. Validación con múltiples lentes, sin razonamiento y con familias diferentes, con comprobantes que se pueden reproducir.

## Instalar

Instale la CLI `prism` (y el servicio HTTP) en su PATH:

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

¿No usa Python? Use el iniciador de npm (descarga y verifica SHA256 de un binario precompilado):

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

O agréguelo como una biblioteca; extras: `[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`:

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## Inicio rápido

Prism siempre valida con una familia de modelos **diferente** a la del llamante (Bloqueo 1), por lo que
configure al menos un proveedor de familia alternativa. Establezca una clave de firma (o `PRISM_DEV=1`
para pruebas locales) para que se puedan escribir los comprobantes:

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## Arquitectura

Prism aplica cuatro bloqueos arquitectónicos en el contrato de la API:

1. **Familia diferente:** la familia de modelos del llamante siempre se excluye de la validación.
2. **Sin razonamiento:** se elimina el CoT del productor antes de cruzar el límite de la familia.
3. **Múltiples lentes:** se ejecutan al menos 3 lentes independientes en paralelo.
4. **Con conocimiento de la submodularidad:** se rechaza si los lentes están demasiado de acuerdo (señal colapsada).

## Servicio HTTP

Ejecute prism como un servicio HTTP (necesita el extra `[http]`):

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| Punto final | Qué hace |
|---|---|
| `POST /verify` | Valida un artefacto (el mismo contrato que la CLI). Se bloquea dentro del presupuesto; `Prefer: respond-async` + una URL de `webhook` → `202`, el resultado se entrega al webhook (firmado). |
| `GET /replay/{receipt_id}` | El comprobante firmado + `signature_valid`. |
| `POST /verify-receipt` | Valida un comprobante independiente (entre herramientas). |
| `GET /healthz` | Estado activo + familias de validadores configuradas (sin autenticación). |

Establezca las claves de la API (almacenadas de forma segura); prism es **fail-closed**, por lo que `/verify` se rechaza hasta que se configuren las claves
o se opte por la opción de no autenticación local:

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

Los errores son RFC 9457 `application/problem+json`; `POST /verify` respeta una cabecera `Idempotency-Key`
y un límite de velocidad por clave (`429` + `Retry-After`). Los webhooks asíncronos/de escalamiento son
Standard-Webhooks-signed, con protección SSRF (sin destinos internos/de metadatos), se reintentan y llevan un
compensador de eventos de cancelación con nombre.

## Comprobantes y firma (Ed25519, verificable por cualquier persona)

Cada validación produce un comprobante firmado y reproducible en `~/.prism/receipts.db`. v0.4 firma
los nuevos comprobantes con **Ed25519 (RFC 8032)** de forma predeterminada, por lo que **una herramienta diferente puede verificar un comprobante de prism con la clave pública de prism; no se necesita una clave compartida**:

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

La firma cubre el resultado, los hashes del artefacto pre/post-strip, el modelo de validador, la
matriz de submodularidad, los hashes de los prompts por lente (reproducibles byte por byte), los pines de recuperación de citas y el `alg`/`kid` de firma. Los comprobantes **HMAC** heredados siguen siendo válidos (establezca
`PRISM_SIGNING_SECRET`); `PRISM_DEV=1` genera una clave de desarrollo para pruebas locales. Prism **se niega a iniciar**
los caminos de verificación/reproducción/servicio/MCP si no se configura ninguna clave, en lugar de firmar silenciosamente
con una clave conocida públicamente.

Administre los comprobantes almacenados con los comandos del compensador:

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## Seguridad y privacidad

- **Modelo de amenazas.** Prism lee el artefacto + la intención que se le pasa y las respuestas de los modelos de validador, y escribe comprobantes firmados en una base de datos SQLite local. **No** lee
su árbol de código fuente, entorno ni credenciales más allá de las claves de la API del proveedor que proporciona a través de
las variables de entorno. Las firmas de los comprobantes brindan **verificabilidad de terceros** (Ed25519: un
consumidor verifica con la clave pública, sin clave compartida), pero no son a prueba de manipulaciones contra un
atacante con acceso raíz local que pueda leer la clave privada almacenada; este es el mismo límite que la clave secreta HMAC. Para una resistencia genuina a las manipulaciones, almacene la clave en un HSM y ancle los comprobantes en un
registro de transparencia (el camino de endurecimiento con nombre).
- **Superficie HTTP.** `prism serve` se enlaza a la interfaz de bucle local de forma predeterminada, es **fail-closed** (sin `/verify`
sin claves de la API), almacena las claves de forma segura y **protege contra SSRF** las URL de webhook proporcionadas por el llamante
(sin destinos internos/de enlace local/de metadatos). Ejecuta los artefactos proporcionados por el llamante a través de un modelo;
un artefacto puede *intentar* la inyección de prompts, pero no puede cambiar el esquema del resultado ni extraer
las claves del proveedor de prism.
- **Sin telemetría.** Prism envía solicitudes solo a los proveedores de modelos que configure
(Anthropic / OpenAI / Google / Ollama local). Nada más.
- Política completa: [SECURITY.md](SECURITY.md).

## Licencia

MIT
