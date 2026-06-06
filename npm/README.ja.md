<p align="center">
  <a href="README.md">English</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

[`prism`](https://github.com/mcp-tool-shop-org/prism-verify) CLIの、前提条件なしの**npx**によるインストール。これは、実行時のLLM検証ツールです（モデルの種類が異なり、推論機能は制限され、多角的な検証を行い、Ed25519署名付きのトランザクションレシートを使用します）。

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

これは、[`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher) のためのシンプルなラッパーです。プラットフォーム固有の`prism`バイナリを、[prism-verify GitHub リリース](https://github.com/mcp-tool-shop-org/prism-verify/releases)からダウンロードし、**SHA256チェックサムを検証**し、キャッシュ（`~/.cache/mcptoolshop/prism/<version>/`）に保存し、実行します。ネットワークアクセスはHTTPSのみで、GitHubに限定されます。テレメトリや認証情報は保存されません。

**Pythonパッケージの方が使いやすいですか？** `uv tool install prism-verify` / `pipx install prism-verify`（PyPI、PEP 740に準拠した信頼性証明付き）。npmラッパーは、Pythonを使用しない`npx`での利用を想定しています。バンドルされたバイナリには、CLI、ローカル（Ollama）検証、HTTPサービス、引用検証（オプションで自己ホスト型の根拠検証ツールを含む）、および`prism eval`キャリブレーションベンチマークが含まれます。ホストプロバイダー検証ツール（Anthropic / OpenAI / Google）およびその他の機能は、PyPIインストールに含まれます。

完全なドキュメント、セキュリティモデル、およびソースコード：<https://github.com/mcp-tool-shop-org/prism-verify>。

MIT © mcp-tool-shop
