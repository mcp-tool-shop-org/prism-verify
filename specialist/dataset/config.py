"""Verifier (L4 Groundedness) puzzle-curriculum config — mirrors the budgeter's token-budget template.
Claim+evidence -> {supported|unsupported|abstain}; the gold label is known BY CONSTRUCTION (we plant
the swap), so the curriculum is self-checkable with NO human grading — exactly the property that made
the budgeter's computable-answer puzzles work. Teaches the PRINCIPLES of groundedness, not a lookup."""

VERDICTS = ("supported", "unsupported", "abstain")

# Cost-asymmetric (verifier kickoff): a false "supported" (ships a hallucination) is far worse than a
# false "unsupported" (wastes a generalist call). Eval weights false-confirms this many times.
COST_FP_OVER_FN = 5

SYSTEM_PROMPT = (
    "You are a Groundedness Verifier. Given EVIDENCE and a CLAIM, decide whether the evidence "
    "supports the claim. Check every load-bearing part of the claim against the evidence. Answer "
    "'supported' (every part traces to the evidence), 'unsupported' (some part is contradicted or "
    "not present in the evidence), or 'abstain' (the evidence is silent — insufficient to judge). "
    "Reason briefly, then give the one-word verdict."
)

# Record schema = verifier kickoff's contract + the puzzle-curriculum additions (level/principle/etc.)
SCHEMA_FIELDS = [
    "id", "level", "type", "evidence", "claim", "verdict", "reasoning", "principle",
    "hard_negative", "corruption", "multi_hop", "source", "real_question", "split",
]

PRINCIPLES = {
    1: "Every load-bearing part of a supported claim appears in the evidence.",
    2: "Fluency is a red herring — a claim can paraphrase the evidence yet flip one entity, number, "
       "or relation the evidence never states. That is a hallucination, not a restatement. But a "
       "meaning-preserving paraphrase that keeps the relation's direction (e.g. active vs passive "
       "voice) IS a faithful restatement — supported.",
    3: "A compound claim is supported only if EVERY part traces; one untraceable part flips the verdict.",
    4: "Some claims are true only by combining two or more evidence spans — miss a hop and it no "
       "longer traces.",
    5: "Absence of evidence is not evidence of contradiction. When the evidence does not address the "
       "claim at all, ABSTAIN — say 'I don't know' rather than guess. (Contradicted/swapped claims are "
       "L2's job; L5 is purely the abstain discipline, to avoid redundancy.)",
}

REAL_QUESTION = ("Real one: given a load-bearing claim and the provided sources, decide whether every "
                 "part of the claim traces — supported, unsupported, or abstain.")
