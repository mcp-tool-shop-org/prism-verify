"""5-rung self-checkable groundedness curriculum — now emitting CONTRAST GROUPS, the load-bearing
budgeter lesson. Raw per-record accuracy is shortcut-inflated; what tells the truth is flip-consistency
= the model gets EVERY member of a contrast group right. Each group holds members that are SURFACE-NEAR
but verdict-DIFFERENT, so the only way to be right is the actual groundedness check — never the level,
length, or fluency.

Two anti-shortcut axes (defeat the level->verdict surface shortcut):
  * evidence-anchored: fix the evidence, vary the claim — faithful (supported) vs one-swap (unsupported).
  * claim-anchored:    fix the claim, vary the evidence — supporting (supported) vs silent (abstain).

Rungs map to the Verifier's certification levels:
  L1 trace-the-claim        — supported claim's parts all appear in the evidence   (warm-up)
  L2 plausible-but-unsupported — fluent paraphrase, one planted swap                (THE trap)
  L3 partial / insufficient — compound claim, one conjunct traceable or not         (the decision)
  L4 multi-hop              — true via two spans; break a hop and it goes silent     (the hard case)
  L5 contradicted-vs-silent — abstain when the evidence is silent                    (the discipline)
Every gold label is known by construction -> self-checkable, no human grading.
"""
import config
import corrupt as C


def _rec(level, type_, evidence, claim, verdict, reasoning, *, pair_id, contrast, corruption,
         hard_negative, multi_hop=False, source="synthetic-rule"):
    return {
        "level": level, "type": type_, "evidence": evidence, "claim": claim, "verdict": verdict,
        "reasoning": reasoning, "principle": config.PRINCIPLES[level], "hard_negative": hard_negative,
        "corruption": corruption, "multi_hop": multi_hop, "source": source,
        "real_question": config.REAL_QUESTION,
        "pair_id": pair_id,         # members of one contrast group share this -> flip-consistency unit
        "contrast": contrast,       # False = the anchor member, True = the flipped twin
    }


# ── evidence-anchored group: fix evidence, vary claim (faithful supported vs one-swap unsupported) ──

def evidence_group(ev, pair_id):
    """L1 faithful (supported) + L2 one-swap twin (unsupported), SAME evidence. The two claims differ by
    a single planted swap, so length/fluency cannot predict the verdict — only the swap does. Returns
    None if no swap is constructible (so the pair is never half-built)."""
    r = C.corrupt(ev)
    if not r:
        return None
    swapped, desc = r
    return [
        _rec(1, "trace-the-claim", ev, ev, "supported",
             "The claim restates the evidence; every load-bearing part traces.",
             pair_id=pair_id, contrast=False, corruption="none (faithful)", hard_negative=False),
        _rec(2, "plausible-but-unsupported", ev, swapped, "unsupported",
             f"The claim reads fluently but flips one part the evidence never states ({desc}); the rest "
             f"matching is the red herring — partial match is not support.",
             pair_id=pair_id, contrast=True, corruption=desc, hard_negative=True),
    ]


# ── claim-anchored group: fix claim, vary evidence (supporting supported vs silent abstain) ──────────

def claim_group(claim, ev_support, ev_silent, pair_id):
    """The strongest anti-shortcut: ONE claim judged against three evidences -> three verdicts, so the
    claim surface is identical and the model MUST read the evidence. supporting->supported,
    contradicting->unsupported (planted negation), silent->abstain. Falls back to the supported+abstain
    pair if no negation is constructible. This 3-way triple also evens the verdict balance (every
    verdict appears once per group). L5 stays abstain-only; the contradiction member is an L2 unsupported."""
    out = [
        _rec(1, "trace-the-claim", ev_support, claim, "supported",
             "The evidence states the claim directly; every load-bearing part traces.",
             pair_id=pair_id, contrast=False, corruption="none (faithful)", hard_negative=False),
        _rec(5, "abstain-when-silent", ev_silent, claim, "abstain",
             "The evidence is about a different topic and says nothing about the claim — absence of "
             "evidence is not contradiction, so abstain rather than guess.",
             pair_id=pair_id, contrast=True, corruption="evidence silent (unrelated)", hard_negative=True),
    ]
    neg = C.negate(ev_support)
    if neg:
        contra_ev, desc = neg
        out.insert(1, _rec(2, "plausible-but-unsupported", contra_ev, claim, "unsupported",
                           "The evidence directly contradicts the claim — it states the opposite, so the "
                           f"claim is not supported ({desc}).",
                           pair_id=pair_id, contrast=True, corruption=desc, hard_negative=True))
    return out


# ── voice group (L2): same relation, active paraphrase (supported) vs direction-reversed (unsupported) ─

def voice_group(subj, verb_active, verb_passive, obj, pair_id):
    """Voice-invariance — the v2 fix. The evidence states a relation in the PASSIVE voice. A claim in
    the ACTIVE voice is the SAME relation -> supported (changing voice is meaning-preserving). The
    DIRECTION-REVERSED claim swaps subject and object -> unsupported. Pins the distinction v1 conflated:
    it over-flagged faithful active/passive paraphrases as unsupported. Surface-near, verdict-different;
    crucially the reversed negative keeps the relation-direction discipline intact."""
    ev = f"{obj} {verb_passive} {subj}."
    active_same = f"{subj} {verb_active} {obj}."
    reversed_dir = f"{obj} {verb_active} {subj}."
    ev, active_same, reversed_dir = (s[0].upper() + s[1:] for s in (ev, active_same, reversed_dir))
    return [
        _rec(2, "voice-invariant", ev, active_same, "supported",
             "Same relation as the evidence, restated in the active voice — a meaning-preserving "
             "paraphrase (voice is not content), so every load-bearing part traces: supported.",
             pair_id=pair_id, contrast=False, corruption="active/passive paraphrase (faithful)",
             hard_negative=True),
        _rec(2, "voice-invariant", ev, reversed_dir, "unsupported",
             "Subject and object are swapped, reversing the relation's direction; the evidence states "
             "the opposite direction, so the claim is not supported.",
             pair_id=pair_id, contrast=True, corruption="relation direction reversed", hard_negative=True),
    ]


# ── conjunct group (L3): same base claim, second conjunct traceable (supported) or not (unsupported) ─

def conjunct_group(ev, traceable_2nd, untraceable_2nd, pair_id):
    """A compound claim is supported only if EVERY conjunct traces. Same first conjunct (from ev), the
    second is either present in ev (supported) or absent (unsupported) — defeats 'compound -> unsupported'."""
    base = ev.rstrip(".")
    def _join(second):
        s = second.rstrip(".")
        return f"{base}, and {s[0].lower() + s[1:]}."
    return [
        _rec(3, "partial-insufficient", f"{ev} {traceable_2nd}", _join(traceable_2nd), "supported",
             "Both conjuncts trace — the first to the first evidence sentence, the second to the "
             "second; a fully-supported compound.",
             pair_id=pair_id, contrast=False, corruption="both conjuncts traceable", hard_negative=False),
        _rec(3, "partial-insufficient", ev, _join(untraceable_2nd), "unsupported",
             "The first conjunct traces but the second is not in the evidence, so the compound is "
             "unsupported — partial support is not support.",
             pair_id=pair_id, contrast=True, corruption="appended an unsupported conjunct",
             hard_negative=True),
    ]


# ── hop group (L4): both spans present (supported) vs one hop removed -> silent (abstain) ────────────

def hop_group(ev1, ev2, bridge_claim, pair_id):
    """The bridge claim follows only by combining ev1 + ev2. With both present -> supported. Remove the
    second hop and the bridge is no longer addressed -> abstain (silent), not a guess. Defeats
    'multi-hop-shaped -> supported'."""
    return [
        _rec(4, "multi-hop", f"{ev1} {ev2}", bridge_claim, "supported",
             "The claim follows only by combining both evidence sentences — a two-hop trace; each hop "
             "alone is insufficient but together they support it.",
             pair_id=pair_id, contrast=False, corruption="none (both hops present)", hard_negative=False,
             multi_hop=True),
        _rec(4, "multi-hop", ev1, bridge_claim, "abstain",
             "Only the first hop is present; the bridging fact is missing, so the evidence does not "
             "address the full claim — abstain rather than assume the second hop.",
             pair_id=pair_id, contrast=True, corruption="second hop removed (silent)", hard_negative=True,
             multi_hop=True),
    ]


def to_sft(p):
    """puzzle record -> OpenAI-messages SFT (identical shape to the budgeter)."""
    user = f"EVIDENCE:\n{p['evidence']}\n\nCLAIM:\n{p['claim']}"
    assistant = f"<think>\n{p['reasoning']}\n</think>\n\n{p['verdict']}"
    return {"messages": [
        {"role": "system", "content": config.SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}
