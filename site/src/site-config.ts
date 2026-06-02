import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'prism-verify',
  description:
    'Runtime LLM verifier — a different model family, reasoning-stripped, multi-lens, with signed Ed25519 receipts anyone can check.',
  logoBadge: 'PV',
  brandName: 'prism-verify',
  repoUrl: 'https://github.com/mcp-tool-shop-org/prism-verify',
  npmUrl: 'https://www.npmjs.com/package/@mcptoolshop/prism-verify',
  footerText:
    'MIT Licensed — built by <a href="https://github.com/mcp-tool-shop-org" style="color:var(--color-muted);text-decoration:underline">mcp-tool-shop-org</a>',

  hero: {
    badge: 'Runtime verifier · v0.4',
    headline: 'Verify what your agents produce —',
    headlineAccent: 'before it ships.',
    description:
      'prism adjudicates code, tool-calls, and citations with a model family different from the caller\'s, the producer\'s reasoning stripped, and at least three decorrelated lenses — then emits a signed, replayable receipt anyone can verify. CLI · MCP · HTTP.',
    primaryCta: { href: '#usage', label: 'Get started' },
    secondaryCta: { href: 'handbook/', label: 'Read the Handbook' },
    previews: [
      { label: 'Install (PyPI)', code: 'uv tool install prism-verify' },
      { label: 'Install (npx)', code: 'npx @mcptoolshop/prism-verify --help' },
      {
        label: 'Verify',
        code: 'prism verify -a @code.py -i "sort in O(n log n)" --caller-family openai',
      },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'Four locks, enforced at the API contract',
      subtitle: 'Why a prism verdict is trustworthy where a self-check is not.',
      features: [
        {
          title: 'Family-different',
          desc: "The caller's model family is excluded from the verifier by construction — no model grades its own homework, even under provider outage.",
        },
        {
          title: 'Reasoning-stripped',
          desc: "The producer's chain-of-thought is stripped before it crosses the family boundary, so a manipulated trace can't inflate the verdict.",
        },
        {
          title: 'Multi-lens, submodular',
          desc: 'At least three decorrelated lenses run in parallel; prism refuses if they collapse to a single redundant signal.',
        },
        {
          title: 'Independently-verifiable receipts',
          desc: 'Every verdict emits a replayable Ed25519 receipt a different tool verifies with prism\'s public key — no shared secret.',
        },
        {
          title: 'Citation verification',
          desc: 'A deterministic retrieval floor (arXiv/Crossref) + a numeric guard gate a RAG-fed groundedness lens — fabrications refuse, not pass.',
        },
        {
          title: 'CLI · MCP · HTTP',
          desc: 'Same guarantees from the `prism` CLI, an MCP server, and a FastAPI service (`prism serve`) — pick the surface your workflow needs.',
        },
      ],
    },
    {
      kind: 'code-cards',
      id: 'usage',
      title: 'Usage',
      cards: [
        {
          title: 'Install',
          code: 'uv tool install prism-verify\n# or: pipx install prism-verify\n# or, zero Python:\nnpx @mcptoolshop/prism-verify --help',
        },
        {
          title: 'Verify an artifact',
          code: 'export PRISM_DEV=1   # local dev signing key\nprism verify \\\n  --artifact @myfile.py \\\n  --intent "Sort a list in O(n log n)" \\\n  --caller-family openai --provider ollama',
        },
        {
          title: 'Run as an HTTP service',
          code: 'prism serve --port 8000\n# POST /verify · GET /replay/{id} · POST /verify-receipt · OpenAPI at /docs',
        },
        {
          title: 'Verify a receipt cross-tool (no shared secret)',
          code: 'prism keygen --out signing_key.pem && prism pubkey > prism-pub.pem\nprism verify-receipt receipt.json --public-key prism-pub.pem',
        },
      ],
    },
  ],
};
