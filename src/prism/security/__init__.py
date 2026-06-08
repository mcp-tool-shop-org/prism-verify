"""prism.security — injection-hardening stage (per-duty, opt-in, fail-open, cert-preserving).

Design: design/specialist-injection-hardening-dispatch.md (study-swarm wf_cbbbe6fb-917, gate
receipt prism-01ktkq71ezb7vc6xh3n4xtxn5j). v0 ships the model-free core: input de-smuggling on a
COPY of judged content. Follow-ons (Mike-gated): a contamination pre-filter -> fail-open ABSTAIN,
spotlighting for the non-certified general-model lenses, and a deception/honeypot attribution layer.

Invariant across the whole stage: NEVER mutate a certified specialist's input. Hardening operates on
the content the fleet SCREENS, not the bytes a frozen judge sees, so the fixed-input-shape
certification (flip-consistency + held-out OOD gate) is preserved by construction.
"""

from prism.core.types import ModelFamily
from prism.security.normalize import NormalizationReport, desmuggle
from prism.security.spotlight import Spotlighted, spotlight

# Families whose certification depends on a FIXED input shape — their input is NEVER transformed
# (no spotlight / datamark / re-template). They are hardened by an input-untouched contamination
# pre-filter instead (design/specialist-injection-hardening-dispatch.md, finding 1; Ovadia 2019,
# arXiv:1906.02530 — any input transform is a distribution shift that voids the OOD certification).
CERTIFIED_FROZEN_FAMILIES: frozenset[ModelFamily] = frozenset(
    {ModelFamily.LOCAL_VERIFIER, ModelFamily.LOCAL_SYCOPHANCY}
)

__all__ = [
    "CERTIFIED_FROZEN_FAMILIES",
    "NormalizationReport",
    "Spotlighted",
    "desmuggle",
    "spotlight",
]
