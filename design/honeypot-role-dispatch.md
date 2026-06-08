# A deception / honeypot role for the oversight fleet — research-grounded design dispatch

**Status:** Step-4 citation gate RUN (locked path `roleos verify-citations` → prism). **Verdict `escalate`
(advisory, non-blocking); 0 FABRICATED, 0 MISATTRIBUTED across all 10 parsed arXiv citations.** Signed receipt
`prism-01ktkspbqa2j3kwf66bqrgpf01`; full result `design/honeypot-role-gate-result.json`. **5 full ACCEPT** incl.
the two critic-surfaced load-bearing papers — **The Attacker Moves Second [12]** (the hard ship-gate) and **the
Honeypot Protocol [32]** (the scheming-judge fork) — plus Kill-Chain Canaries [6], CaMeL [30], the MTD survey
[14]. The 5 `not_addressed`→escalate are existence-RESOLVED, groundedness-from-abstract conservative (DataFlip
[11], shelLM [7], Secret Sharer [8], the deception survey [4], Deception-in-Depth [24] — body-sourced; DataFlip
was ACCEPT in this session's prior gates). The 4 unparsed are vendor-doc / multi-source lines (Thinkst [2], CHeaT
[5], shelLM/Canary's-Echo) — all WebSearch-corroborated this session; the mature-deception sources (Spitzner,
Thinkst, NVIDIA, Gartner, Kerckhoffs) are oracle-external by nature. No finding is load-bearing on an unverified
citation. **Authored:** 2026-06-08. **Via:** study-swarm `wf_ed53ef49-8ef` (5 web-research agents
+ a completeness critic) — fired on Mike's "what if we made a honeypot role" (an explicit deception-layer design
question; the mature security-deception field is a textbook "adjacent domain already solved a version"). **Scope:**
whether/how to add a deception/honeypot role to the runtime oversight fleet, as the active-attribution upgrade of
the two passive guards in the hardening design (abstain-spike attribution + the KAD canary), and the answer to
DataFlip's "a detector the attacker knows about is evadable." NOT a build order — a Mike-gated design, **with a
hard empirical gate before any ship.**

## The decision (up front)

**A honeypot role is viable and well-grounded — but only in ONE specific shape, and it must not ship until one
empirical test passes.** The naive form ("plant a honey-instruction; trip when the judge FOLLOWS it") is exactly
known-answer detection, which DataFlip drives to ~1.5% detection / 88% malicious success [11]. The sound form
inverts the trip:

> **Trip on the PRESENCE of a secret, per-call marker in downstream output (the kill-chain "Executed" stage) —
> NOT on the model executing a known probe.** The trap's value is the SECRECY the attacker cannot fingerprint
> (Spitzner's near-zero-FP-by-construction [1] + Kerckhoffs [20]), realized as a content-channel CANARY TOKEN:
> `trap = KDF(sealed_seed, call_id, rotation_epoch)` over a typed bank that rotates **FORM** (phrasing ×
> insertion-point × decoy persona), not just value (the DataFlip lesson: the *template's* predictability is
> attacked, not the secret's value). Planted ONLY in the normalized **screening copy** — never the certified
> judge's input — and **observe-and-log / fail-open**: a trip can attribute + quarantine a content-stream but
> **never flips a verdict** (routed through CaMeL-style capability gating [30]). Owned by a standing Role-OS
> **deception role** (the DDP layer [6]) that holds the seed, rotates traps, attributes trips, and feeds confirmed
> signatures into recert — but that role is **the highest-privilege, least-verified actor in the fleet**, so it is
> sandboxed + decorrelated accordingly.

**Hard gate (do NOT ship until this passes):** the load-bearing claim "rotation defeats an adaptive attacker" is
**reasoned, not measured.** *The Attacker Moves Second* [12] broke 12 recent PI/jailbreak defenses (incl.
secret-knowledge mechanisms) at >90% ASR with adaptive RL/search attacks. An output-observing attacker can plausibly
learn to **avoid** tripping rotated bait (act only on whitelisted-form instructions, stay conservative) rather than
evade detection of a fixed probe. **Gate condition: test rotation survival against an Attacker-Moves-Second-style
adaptive, output-observing adversary before the role goes live.**

## Research grounding (the empirical floor — verified at Step-4)

Format: `N. **finding.** Authors year (id). → implication.` ⚠ = 2026 preprint. †= oracle-external (vendor doc /
standard / law review / canon) — existence WebSearch-corroborated, never silently load-bearing.

### A. Deception primitives + the near-zero-FP-by-construction property
1. **A honeypot/honeytoken is a resource with NO production value, so any interaction is anomalous by definition — detection by logical impossibility, not signatures.** Spitzner 2003 (ACSAC 2003, "Honeypots: Catching the Insider Threat").† → The whole role rests on this: a honey-marker with zero legitimate purpose gives near-zero FP without a statistical threshold — sound exactly where the contamination pre-filter (a signature/ML detector) is adaptively evadable.
2. **Canary tokens are unique embeddable tripwires (URLs, docs, keys) that fire on access and almost never on benign activity, because triggering requires an attacker to actively use them.** Thinkst Applied Research 2025 (canarytokens.org / canary.tools docs).† → The operational form to copy: a unique, rotated marker whose mere appearance downstream fires the trip — exact-string detection, no model self-verification (satisfies EXTERNAL_VERIFIER).
3. **Canaries placed where no benign user would reach make any trigger a high-confidence policy violation with few false positives (demonstrated injecting canary tokens into serialized model files).** NVIDIA AI Red Team 2024 (developer.nvidia.com blog).† → Direct precedent for canaries in the AI artifact channel: the honey-marker lives in the screening copy a correct judging pass never "reaches" (it treats content as inert data), so a trip attributes a data/instruction-boundary breach — the exact indirect-injection failure — at near-zero FP.
4. **Three decades of active-defense deception (honeypots, honeytokens, MTD) reviewed: deception's value is forcing the attacker to act in a monitored space where any move is signal.** Zhang & Thing 2021 (arXiv:2104.03594, Computers & Security). → Grounds the role in a mature field rather than first principles; the deception-in-depth layering + DDP concepts come from here, not invention.

### B. LLM-specific honeypots / honeytokens / injection canaries (2023-2026)
5. **Cloak-Honey-Trap embeds string payloads into untrusted assets to defend against autonomous LLM agents; its "Honey" stage plants tokens that fingerprint a hijacked agent — distinct from "Trap" (state-corrupting token landmines).** Ayzenshteyn, Weiss & Mirsky 2025 (USENIX Security 2025, CHeaT). → The closest direct analogue: validates planting a honey-token only a hijacked LLM acts on. **Borrow "Honey"; explicitly DROP "Trap"** (state corruption violates fail-open + no-self-poisoning).
6. **Kill-Chain Canaries track prompt injection by STAGE (Exposed → Persisted → Relayed → Executed) across attack surfaces and model tiers (950 runs, 5 LLMs; Claude 0/164 at memory-write, GPT-4o-mini ~53%).** Wang 2026 (arXiv:2603.28013). ⚠ → The implementation template: instrument the trip as the kill-chain "Executed" stage (marker present in output), and track partial trips (Exposed/Relayed) for early attribution. A preprint → a design pattern, not a guarantee.
7. **LLM-powered honeypots (shelLM) and agent honeypots monitor real attacker/agent interaction in the wild (the LLM Agent Honeypot saw ~8 likely AI agents of ~8M requests — extreme selectivity).** Sladic et al. 2023 (arXiv:2309.00155); Reworr & Volkov 2024 (arXiv:2410.13919). → The ~8/8M figure is the closest empirical anchor for the near-zero-FP claim, and the standing deception-ops role mirrors these monitoring deployments.
8. **The Secret Sharer + The Canary's Echo: planted canary sequences measure unintended memorization / privacy leakage in models and LLM-generated text.** Carlini et al. 2019 (arXiv:1802.08232); Meeus et al. 2025 (arXiv:2502.14921). → The canary-in-the-corpus precedent for the CITATION duty's RAG channel (detecting corpus poisoning / training-data echoes), a non-text-channel extension of the role.

### C. The crux — and the hard adversarial gate
11. **DataFlip adaptively evades known-answer detection (the secret lives in the attacker's view): a handcrafted IF/ELSE payload returns the key when probed yet executes the injection otherwise — detection as low as 1.5%, malicious success up to 88%, no white-box access.** Choudhary, Anshumaan, Palumbo & Jha 2025 (arXiv:2507.05630). → The exact limit the role must beat: a detector whose mechanism is in the attacker's view is evadable → the trip must depend on marker SECRECY+PRESENCE, not on the model executing a known probe; rotate FORM so there is no fixed template to attack.
12. **A general adaptive-attack framework (gradient + RL + search + human red-team) bypassed 12 recent defenses — prompting, adversarial training, filtering, AND secret-knowledge mechanisms — at >90% ASR; defenses tested against static/weak attackers are misleading.** Nasr, Carlini, Sitawarin et al. 2025 (arXiv:2510.09023, "The Attacker Moves Second"). → **The hard gate.** "Secret-knowledge mechanisms" includes canary/secret-based defenses → the honeypot's rotation-beats-adaptive-attacker thesis MUST be evaluated against an adaptive, output-observing adversary before shipping; an attacker may learn to AVOID the bait, not just evade detection.

### D. Keeping the trap unfingerprintable — rotation, MTD, Kerckhoffs
14. **Moving-target defense systematically shifts the attack surface so a previously-learned exploit no longer applies (survey of network MTD).** Sengupta et al. 2019 (arXiv:1905.00964, IEEE COMST). → The principle behind rotating the trap's FORM each epoch; the direct counter-pattern to "attacker fingerprints a fixed decoy."
20. **Kerckhoffs's principle: a system must stay secure with everything public except the key.** Kerckhoffs 1883 (canon).† → Resolves secrecy-vs-auditability: publish the mechanism, keep only the SEED secret; `trap = KDF(seed, call_id, epoch)` is byte-replayable from logged `(call_id, epoch)` without revealing the seed — but see the seed-custody fork below.
21. **Honeypot fingerprinting + property-based / coverage-guided generation** — Future Internet 2025 honeypot-fingerprinting review†; Hughes/Lampropoulos coverage-guided PBT (OOPSLA 2019).† → Generate the trap bank as a property-checked family (diverse phrasing/insertion-point) so attackers can't enumerate it; audit the bank for self-fingerprinting tells.

### E. Sound attribution + the deception-ops role
24. **Deception-in-depth: multiple layered deception types raise the odds an attacker trips at least one, and cross-layer correlation strengthens attribution.** Landsborough, Rowe, Nguyen & Fugate 2024 (arXiv:2412.16430). → Layer the content-channel canary + the observe-only honeypot judge + the abstain-spike signal; a trip on one corroborates the others for sound attribution.
25. **Honeytoken trips are high-fidelity, low-volume signals — the OPPOSITE of the SOC alert-fatigue problem — and route to SOAR-style playbooks (quarantine, capture, signature-extract).** Acalvio / Radiant Security (vendor docs)† + Spitzner [1]. → The deception-ops role triages trips into quarantine-the-stream + capture-the-signature → recert feed, not raw escalation; this is why deception alerts don't drown the human queue the way detector FPs do.

### F. Capability-gating the trip (what a trip may DO)
30. **CaMeL defeats prompt injection by design via control/data-flow separation + capability metadata, model UNMODIFIED (77% provable-secure task completion vs 84% undefended on AgentDojo).** Debenedetti et al. 2025 (arXiv:2503.18813, DeepMind). → The load-bearing primitive for the "gate what a trip can DO" half: a trip attributes + quarantines a content-stream but is capability-gated so it can NEVER flip a verdict or trigger a downstream action — keeps the role fail-open + the moat intact.

### G. The threat-model fork the swarm under-covered (critic-surfaced)
32. **The Honeypot Protocol tests context-dependent AI behavior by varying ONLY the system prompt across eval / synthetic-deployment / no-monitoring conditions (Claude Opus 4.6 in BashArena was uniform across conditions, no scheming detected).** Hasan 2026 (arXiv:2604.13301, AI Control Hackathon). ⚠ → A different honeypot purpose: detecting a SCHEMING judge (behaves differently under perceived-weak oversight), not an injected one. The fleet must decide which threat the role addresses — injected judges (the design above) vs misaligned judges (this) — because the bait + attribution logic differ.

## The recommended design (sound shape, tensions resolved where the evidence allows)
- **Primitive:** a content-channel **canary token** (rotated honey-marker), planted ONLY in the normalized screening copy [2,3,5].
- **Trip:** marker **PRESENCE** in downstream output (kill-chain "Executed" [6]) — NOT instruction-execution (avoids the DataFlip-evadable KAD variant [11]).
- **Rotation:** `KDF(sealed_seed, call_id, epoch)` over a typed bank rotating FORM, not value [11,14,21]; Kerckhoffs-public mechanism, secret seed, replayable from `(call_id, epoch)` [20].
- **Posture:** observe-and-log, fail-open, OUT of the certified judge's fixed-shape input (cert preserved); a trip is capability-gated [30] — attributes + quarantines, never flips a verdict.
- **Owner:** a Role-OS deception role (DDP layer [6,4]) for seed custody, rotation, attribution, recert feed [24,25].
- **Layering:** content-canary + observe-only honeypot judge + abstain-spike → deception-in-depth [24].

## Open forks (need a decision — the critic's load-bearing tensions)
1. **Seed custody.** Whoever holds the KDF seed can FORGE trips, and the deception role plants instructions everywhere → it is the highest-privilege/least-verified actor. Who holds the seed? How is the role sandboxed + its own actions attributable? (No source resolves this — it's a studio architecture decision.)
2. **The honeypot judge trips on its own bait.** If the observe-only honeypot judge reads the baited screening copy and is itself an LLM, IT is the most likely thing to "execute" the bait. It must read **pre-bait** content or be excluded from the baited copy — unresolved in the research, an architectural must-fix.
3. **Per-trip vs spike-gated.** "Any interaction = malicious" (per-trip containment, but DoS-able by trip-spamming) vs "treat a spike as the signal" (resists flood, but weakens the near-zero-FP property + delays response). Pick one per surface.
4. **Injected-judge vs scheming-judge threat model** [32] — different bait, different attribution. The fleet's current model is "external attacker injects via content"; decide whether the role also covers misalignment.
5. **Decorrelation at ~14B** — the deception role's "different family" buys less independence when the local ~14B family pool shares pretraining ancestry; the same correlated-errors caveat from the fleet dispatch applies.

## Standards compliance (the six — scored 0-3)
| Standard | Score | Evidence |
|---|---|---|
| PIN_PER_STEP | **2** | Swarm script + run-id `wf_ed53ef49-8ef` persisted; the KDF-from-seed design is explicitly byte-replayable from logged `(call_id, epoch)` [20] — but the seed-custody fork is open. |
| ANDON_AUTHORITY | **2** | Step-4 gate halts on fabricated/misattributed; the **hard ship-gate** (adaptive-attacker test [12]) is an explicit ANDON before the role goes live. |
| NAMED_COMPENSATORS | **2** | Canon-write (dispatch). `revert_dispatch_commit`; propagation → `requalify_dependent_slices`; paid subagents = bounded owner-accepted cost. No skip. A LIVE honeypot would add irreversible actions (planting bait, quarantine) → its own compensators table at build time. |
| DECOMPOSE_BY_SECRETS | **2** | One agent per design question; the deception role is itself a DECOMPOSE_BY_SECRETS unit (the secret seed is the one volatile, isolated behind the role boundary). |
| UNCERTAINTY_GATED_HUMANS | **2** | Ends in Mike-gated decisions + 5 open forks surfaced with contrastive framing; the design routes trips to uncertainty-gated quarantine, not raw escalation [25]. |
| EXTERNAL_VERIFIER | **3** | Step-4 RUN via `roleos verify-citations` → prism; signed receipt `prism-01ktkspbqa2j3kwf66bqrgpf01`, 0 fabricated / 0 misattributed. The trip mechanism itself also satisfies EXTERNAL_VERIFIER (exact-string marker match, no model self-grading). |

## Mike-gated decisions
1. **Pursue the honeypot role** in the recommended shape (kill-chain canary, marker-presence trip, KDF-rotated FORM, observe-only, capability-gated, Role-OS deception role)?
2. **Accept the hard ship-gate:** no live honeypot until rotation is tested against an adaptive output-observing attacker [12] (this is a build/eval task, not a flip).
3. **Resolve the seed-custody + honeypot-judge-self-trip forks** before any build (forks 1-2 are blocking).
4. **Threat model:** injected-judge only, or also scheming-judge [32]?
5. Sequencing: this folds into the hardening stage's **guarded-abstain / attribution** surface (the piece I deferred). If you greenlight, the first cert-safe, ship-gate-respecting build slice is the **observe-only marker-presence detector + KDF trap bank** (no behavior change, no certified-input change) behind a flag, with the adaptive-attacker eval as its promotion gate.
6. Standing Mike-gates remain OFF: consult flips, `PRISM_SYCOPHANCY_ENDPOINT`, HF publish, any push/commit.
