<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/mcp-tool-shop-org/prism-verify/main/assets/prism-verify-logo.png" alt="prism-verify" width="500">
</p>

<p align="center">
  <a href="https://pypi.org/project/prism-verify/"><img src="https://img.shields.io/pypi/v/prism-verify" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/@mcptoolshop/prism-verify"><img src="https://img.shields.io/npm/v/@mcptoolshop/prism-verify" alt="npm"></a>
  <a href="https://github.com/mcp-tool-shop-org/prism-verify"><img src="https://img.shields.io/badge/source-GitHub-blue" alt="source"></a>
</p>

# @mcptoolshop/prism-verify

Zero-prerequisite **npx** install of the [`prism`](https://github.com/mcp-tool-shop-org/prism-verify)
CLI — a runtime LLM verifier (family-different, reasoning-stripped, multi-lens, signed Ed25519
receipts).

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

This is a thin wrapper over [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher):
it downloads the platform-specific `prism` binary from the
[prism-verify GitHub Release](https://github.com/mcp-tool-shop-org/prism-verify/releases),
**verifies its SHA256 checksum**, caches it (`~/.cache/mcptoolshop/prism/<version>/`), and runs it.
Network access is HTTPS-only to GitHub; no telemetry, no credentials stored.

**Prefer the Python package?** `uv tool install prism-verify` / `pipx install prism-verify`
(PyPI, with PEP 740 provenance attestations). The npm wrapper exists for zero-Python `npx` use; the
bundled binary covers the CLI + local (Ollama) verification + the HTTP service + citation
verification (including an opt-in self-hosted groundedness verifier) + the `prism eval` calibration
benchmark. Hosted-provider verifiers (Anthropic /
OpenAI / Google) and full extras come with the PyPI install.

Full docs, security model, and source: <https://github.com/mcp-tool-shop-org/prism-verify>.

MIT © mcp-tool-shop
