// Step-4 citation gate runner — drives the LOCKED path (roleos runCitationGate -> prism, retrieval
// oracle + different-family ollama groundedness) with a sane timeout (the CLI default 120s x2 is far too
// short for 20 citations). Writes the full gate result (incl. the chained receipt) to a JSON file.
import { runCitationGate } from "file:///E:/AI/role-os/src/verify-citations.mjs";
import { writeFileSync } from "node:fs";

process.env.PRISM_DEV = "1"; // local dev signing key for prism's receipt (inherited by the subprocess)

const DISPATCH = process.argv[2] || "E:/AI/prism-verify/design/sycophancy-wedge-dispatch.md";
const OUT = process.argv[3] || "E:/AI/prism-verify/design/sycophancy-gate-result.json";

const res = runCitationGate(DISPATCH, {
  prismCmd: "E:/AI/prism-verify/.venv/Scripts/prism.exe",
  provider: "ollama",
  callerFamily: "anthropic",
  timeout: 1_500_000, // 25 min — one prism invocation covers all citations sequentially
  retries: 0,
});

writeFileSync(OUT, JSON.stringify(res, null, 2) + "\n");
console.log("VERDICT:", res.verdict, "| reason:", res.reason || "(none)", "| pass:", res.pass,
  "| citations:", (res.citations || []).length, "| unparsed:", (res.unparsed || []).length);
