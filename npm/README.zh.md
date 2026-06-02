<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

无需任何先决条件的 **npx** 安装 [`prism`](https://github.com/mcp-tool-shop-org/prism-verify) 命令行工具——一种运行时大型语言模型（LLM）验证器（针对不同模型系列，去除推理过程，采用多重验证方式，并使用签名 Ed25519 凭证）。

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

这是一个对 [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher) 的轻量级封装：它从 [prism-verify GitHub 发布页面](https://github.com/mcp-tool-shop-org/prism-verify/releases) 下载特定平台的 `prism` 二进制文件，**验证其 SHA256 校验和**，将其缓存到 (`~/.cache/mcptoolshop/prism/<version>/`)，然后运行。网络访问仅限于 HTTPS 协议，连接到 GitHub；不收集遥测数据，也不存储任何凭据。

**更喜欢 Python 包吗？** 使用 `uv tool install prism-verify` / `pipx install prism-verify`（PyPI，带有 PEP 740 来源证明）。npm 封装存在是为了在不使用 Python 的情况下使用 `npx`；捆绑的二进制文件包含命令行工具 + 本地（Ollama）验证 + HTTP 服务 + 引用验证 + `prism eval` 校准基准测试。通过 PyPI 安装，可以获得托管服务提供商验证器（Anthropic / OpenAI / Google）和完整的附加功能。

完整文档、安全模型和源代码：<https://github.com/mcp-tool-shop-org/prism-verify>。

MIT © mcp-tool-shop
