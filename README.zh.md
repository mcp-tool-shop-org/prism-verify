<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

用于代理工作流程的运行时仲裁服务。不同模型族、去除推理过程、多视角验证，并提供可重放的收据。**[登录页面和手册 →](https://mcp-tool-shop-org.github.io/prism-verify/)**

## 安装

将 `prism` CLI（以及 HTTP 服务）安装到您的 PATH 环境变量中：

```bash
uv tool install prism-verify        # or: pipx install prism-verify
```

未使用 Python？使用 npm 启动器（下载 + SHA256 验证预构建的二进制文件）：

```bash
npx @mcptoolshop/prism-verify verify --artifact @file.py --intent "..." --caller-family openai
```

或者将其作为库添加——附加选项：`[anthropic]` `[openai]` `[google]` `[mcp]` `[http]` `[all]`：

```bash
uv add prism-verify
# or
pip install "prism-verify[all]"
```

## 快速入门

Prism 始终使用与调用者不同的模型族进行验证（锁定 1），因此
配置至少一个备用模型族提供程序。设置签名密钥（或 `PRISM_DEV=1`
用于本地测试），以便可以写入收据：

```bash
export PRISM_SIGNING_SECRET="$(openssl rand -hex 32)"
export ANTHROPIC_API_KEY="sk-ant-..."   # alt-family verifier for an OpenAI-family caller

prism verify \
  --artifact @myfile.py \
  --intent "Sort a list in O(n log n)" \
  --caller-family openai \
  --provider anthropic
```

## 架构

Prism 在 API 协议层面强制执行四个架构锁定：

1. **模型族不同**——调用者的模型族始终被排除在验证之外。
2. **去除推理过程**——在跨越模型族边界之前，去除生成模型的 CoT（思维链）。
3. **多视角**——至少有 3 个独立的视角并行运行。
4. **考虑子模性**——如果各个视角达成高度一致（信号崩溃），则拒绝。

## HTTP 服务

将 prism 作为 HTTP 服务运行（需要 `[http]` 附加选项）：

```bash
prism serve --host 127.0.0.1 --port 8000      # OpenAPI docs at /docs
```

| 端点 | 功能 |
|---|---|
| `POST /verify` | 验证一个工件（与 CLI 相同的协议）。在预算范围内运行；`Prefer: respond-async` + 一个 `webhook` URL → `202`，将结果传递到（已签名）的 webhook。 |
| `GET /replay/{receipt_id}` | 已签名的收据 + `signature_valid`。 |
| `POST /verify-receipt` | 验证一个独立的收据（跨工具）。 |
| `GET /healthz` | 活动状态 + 已配置的验证器模型族（无需身份验证）。 |

设置 API 密钥（静态时哈希处理）——prism 采用**失败安全**机制，因此在配置密钥或选择本地无身份验证之前，`/verify` 将被拒绝：

```bash
export PRISM_API_KEYS="<sha256(key1)>,<sha256(key2)>"   # callers send: Authorization: Bearer <key>
export PRISM_WEBHOOK_SECRET="<random>"                  # to sign async/escalate webhook deliveries
# local dev only:
export PRISM_HTTP_ALLOW_NO_AUTH=1
```

错误采用 RFC 9457 `application/problem+json` 格式；`POST /verify` 遵循 `Idempotency-Key`
标头，并对每个密钥设置速率限制（`429` + `Retry-After`）。异步/升级 webhook 是
Standard-Webhooks 签名的，并具有 SSRF 保护（不允许内部/元数据目标），会进行重试，并且包含一个
命名的取消事件补偿器。

## 收据和签名（Ed25519，任何人都可以验证）

每次验证都会生成一个已签名的、可重放的收据，存储在 `~/.prism/receipts.db` 中。v0.4 默认使用 **Ed25519 (RFC 8032)** 对
新的收据进行签名，因此 **不同的工具可以使用 prism 的公钥来验证 prism 收据——无需共享密钥**：

```bash
prism keygen --out ~/.prism/signing_key.pem    # generate an Ed25519 keypair
export PRISM_SIGNING_KEY=~/.prism/signing_key.pem
prism pubkey                                    # publish this public key + kid to consumers

# a consumer (e.g. role-os) verifies a receipt with ONLY the public key:
prism verify-receipt receipt.json --public-key prism-pub.pem
```

签名涵盖结果、预/后处理工件哈希值、验证器模型、
子模性矩阵、每个视角的提示哈希值（逐字节可重放）、引用
检索锚点以及签名 `alg`/`kid`。旧版 **HMAC** 收据仍然有效（设置
`PRISM_SIGNING_SECRET`）；`PRISM_DEV=1` 会为本地测试生成一个开发密钥。如果未配置密钥，prism **将拒绝启动**
验证/重放/服务/MCP 路径，而不是默默地使用公开的密钥进行签名。

使用补偿器命令管理存储的收据：

```bash
prism receipt delete <receipt_id>
prism receipt prune --older-than 90d --yes
```

## 安全性和隐私

- **威胁模型。** Prism 读取您传递的工件 + 意图以及验证器模型的
响应，并将签名的收据写入本地 SQLite 数据库。它**不会**读取您的
源代码树、环境或凭据，除非您通过
环境变量提供的提供程序 API 密钥。收据签名提供**第三方可验证性**（Ed25519：
消费者使用公钥进行验证，无需共享密钥），但不能完全防止本地 root 攻击者读取磁盘上的私钥——这与 HMAC
密钥的上限相同。为了真正提高防篡改能力，请将密钥存储在 HSM 中，并将收据固定在
透明度日志中（命名为强化路径）。
- **HTTP 接口。** `prism serve` 默认绑定到环回地址，采用**失败安全**机制（没有 API 密钥则没有 `/verify`），静态时哈希密钥，并对调用者提供的 webhook URL 进行**SSRF 保护**
（不允许内部/环回/元数据目标）。它将调用者提供的工件传递给模型；
工件可能会*尝试*提示注入，但不能更改结果模式或泄露
prism 的提供程序密钥。
- **无遥测。** Prism 仅向您配置的模型提供程序发送请求
（Anthropic / OpenAI / Google / 本地 Ollama）。除此之外，没有其他操作。
- 完整策略：[SECURITY.md](SECURITY.md)。

## 许可证

MIT
