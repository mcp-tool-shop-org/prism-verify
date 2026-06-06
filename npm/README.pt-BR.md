<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
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

Instalação com **npx**, sem requisitos prévios, do CLI [`prism`](https://github.com/mcp-tool-shop-org/prism-verify) — um verificador de LLM em tempo de execução (diferente por família, sem raciocínio, com múltiplas lentes, com recibos assinados Ed25519).

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

Este é um invólucro simples sobre [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher): ele baixa o binário `prism` específico da plataforma a partir do [prism-verify GitHub Release](https://github.com/mcp-tool-shop-org/prism-verify/releases), **verifica sua soma de verificação SHA256**, armazena em cache (`~/.cache/mcptoolshop/prism/<version>/`) e o executa. O acesso à rede é apenas via HTTPS para o GitHub; sem telemetria, sem credenciais armazenadas.

**Prefere o pacote Python?** `uv tool install prism-verify` / `pipx install prism-verify` (PyPI, com atestações de procedência de acordo com o PEP 740). O invólucro npm existe para uso com `npx` sem Python; o binário incluído cobre o CLI + verificação local (Ollama) + o serviço HTTP + verificação de citação (incluindo um verificador de fundamentação auto-hospedado opcional) + o benchmark de calibração `prism eval`. Os verificadores de provedores hospedados (Anthropic / OpenAI / Google) e recursos adicionais completos vêm com a instalação do PyPI.

Documentação completa, modelo de segurança e código-fonte: <https://github.com/mcp-tool-shop-org/prism-verify>.

MIT © mcp-tool-shop
