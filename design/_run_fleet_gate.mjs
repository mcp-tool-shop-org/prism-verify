// Step-4 citation gate runner for the fleet-receipts dispatch — drives the LOCKED path
// (roleos runCitationGate -> prism, retrieval oracle + different-family ollama groundedness) with an
// extended timeout sized for ~63 citations (arXiv rate-limits the tail of a large burst; one prism
// invocation covers all citations sequentially). Writes the full gate result (incl. the chained receipt).
import { runCitationGate } from "file:///E:/AI/role-os/src/verify-citations.mjs";
import { writeFileSync } from "node:fs";

process.env.PRISM_DEV = "1"; // local dev signing key for prism's receipt (inherited by the subprocess)

const DISPATCH = process.argv[2] || "E:/AI/prism-verify/design/fleet-receipts-dispatch.md";
const OUT = process.argv[3] || "E:/AI/prism-verify/design/fleet-receipts-gate-result.json";

const res = runCitationGate(DISPATCH, {
  prismCmd: "E:/AI/prism-verify/.venv/Scripts/prism.exe",
  provider: "ollama",
  callerFamily: "anthropic",
  timeout: 3_000_000, // 50 min — large citation set + arXiv backoff
  retries: 0,
});

writeFileSync(OUT, JSON.stringify(res, null, 2) + "\n");
console.log("VERDICT:", res.verdict, "| reason:", res.reason || "(none)", "| pass:", res.pass,
  "| citations:", (res.citations || []).length, "| unparsed:", (res.unparsed || []).length);
