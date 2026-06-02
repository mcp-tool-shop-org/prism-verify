<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

Installazione tramite **npx** senza prerequisiti di [`prism`](https://github.com/mcp-tool-shop-org/prism-verify), una CLI (interfaccia a riga di comando) che funge da verificatore LLM in fase di esecuzione (differente a seconda della famiglia di modelli, senza capacità di ragionamento, con molteplici livelli di analisi, con ricevute firmate con Ed25519).

```bash
npx @mcptoolshop/prism-verify verify --artifact @myfile.py --intent "..." --caller-family openai
# or install it on your PATH
npm install -g @mcptoolshop/prism-verify
```

Si tratta di un semplice wrapper per [`@mcptoolshop/npm-launcher`](https://github.com/mcp-tool-shop-org/npm-launcher): scarica il file binario `prism` specifico per la piattaforma dalla [pagina delle release di prism-verify su GitHub](https://github.com/mcp-tool-shop-org/prism-verify/releases), **verifica il checksum SHA256**, lo memorizza nella cache (`~/.cache/mcptoolshop/prism/<versione>/`) e lo esegue. L'accesso alla rete avviene esclusivamente tramite HTTPS con GitHub; non vengono raccolti dati di telemetria né memorizzate credenziali.

**Preferisci il pacchetto Python?** `uv tool install prism-verify` / `pipx install prism-verify` (PyPI, con attestazioni di provenienza conformi a PEP 740). Il wrapper npm esiste per un utilizzo di `npx` senza dipendenze da Python; il file binario incluso copre la CLI, la verifica locale (con Ollama), il servizio HTTP, la verifica delle citazioni e il benchmark di calibrazione `prism eval`. I verificatori per provider ospitati (Anthropic / OpenAI / Google) e le funzionalità aggiuntive complete sono inclusi nell'installazione da PyPI.

Documentazione completa, modello di sicurezza e codice sorgente: <https://github.com/mcp-tool-shop-org/prism-verify>.

MIT © mcp-tool-shop
