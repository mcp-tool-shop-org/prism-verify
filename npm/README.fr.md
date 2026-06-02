<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Installation avec **npx** sans aucune dépendance préalable de [`prism`](https://github.com/mcp-tool-shop-org/prism-verify), l’outil en ligne de commande (CLI) qui est un vérificateur de LLM en temps réel (différentes familles, sans raisonnement, multi-lentilles, avec reçus signés Ed25519).

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

Il s’agit d’une simple couche d’abstraction au-dessus de [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher) : il télécharge le binaire `prism` spécifique à la plateforme à partir de la [version de prism-verify sur GitHub](https://github.com/mcp-tool-shop-org/prism-verify/releases), **vérifie son hachage SHA256**, le met en cache (`~/.cache/mcptoolshop/prism/<version>/`) et l’exécute. L’accès au réseau se fait uniquement via HTTPS vers GitHub ; aucune télémétrie, aucun identifiant stocké.

**Préférez-vous le paquet Python ?** `uv tool install prism-verify` / `pipx install prism-verify` (PyPI, avec attestations de provenance conformes à PEP 740). Le wrapper npm existe pour une utilisation avec `npx` sans Python ; le binaire inclus couvre l’outil en ligne de commande + la vérification locale (Ollama) + le service HTTP + la vérification des citations + le test de calibration `prism eval`. Les vérificateurs de fournisseurs hébergés (Anthropic / OpenAI / Google) et les fonctionnalités supplémentaires sont inclus dans l’installation PyPI.

Documentation complète, modèle de sécurité et code source : <https://github.com/mcp-tool-shop-org/prism-verify>.

MIT © mcp-tool-shop
