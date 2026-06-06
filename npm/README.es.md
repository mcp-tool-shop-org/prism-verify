<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Instalación con **npx** que no requiere dependencias previas de [`prism`](https://github.com/mcp-tool-shop-org/prism-verify), la herramienta de línea de comandos (CLI): un verificador de LLM en tiempo de ejecución (diferente según la familia, sin razonamiento, con múltiples perspectivas y recibos firmados con Ed25519).

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

Esta es una capa delgada sobre [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher): descarga el archivo binario de `prism` específico para la plataforma desde la [versión de GitHub de prism-verify](https://github.com/mcp-tool-shop-org/prism-verify/releases), **verifica su suma de comprobación SHA256**, lo almacena en caché (`~/.cache/mcptoolshop/prism/<versión>/`) y lo ejecuta. El acceso a la red se realiza únicamente a través de HTTPS a GitHub; no se recopilan datos de telemetría ni se almacenan credenciales.

**¿Prefiere el paquete de Python?** `uv tool install prism-verify` / `pipx install prism-verify` (PyPI, con atestaciones de procedencia según PEP 740). El envoltorio de npm existe para el uso de `npx` sin necesidad de Python; el archivo binario incluido cubre la herramienta de línea de comandos, la verificación local (Ollama), el servicio HTTP y la verificación de citas (incluido un verificador opcional de coherencia alojado por el usuario), así como la prueba de calibración de `prism eval`. Los verificadores de proveedores alojados (Anthropic / OpenAI / Google) y las funciones adicionales se incluyen en la instalación de PyPI.

Documentación completa, modelo de seguridad y código fuente: <https://github.com/mcp-tool-shop-org/prism-verify>.

MIT © mcp-tool-shop
