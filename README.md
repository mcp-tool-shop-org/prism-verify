# prism-verify

Runtime adjudication service for agent workflows. Family-different, reasoning-stripped, multi-lens verification with replayable receipts.

## Install

```bash
uv add prism-verify
# or
pip install prism-verify[all]
```

## Quick start

```bash
prism verify --artifact @myfile.py --intent "Sort a list in O(n log n)" --caller-family anthropic
```

## Architecture

Prism enforces four architectural locks at the API contract:

1. **Family-different** — caller's model family is always excluded from verification
2. **Reasoning-stripped** — producer CoT is stripped before crossing the family boundary
3. **Multi-lens** — at least 3 independent lenses run in parallel
4. **Submodularity-aware** — refuses if lenses agree too much (collapsed signal)

## License

MIT
