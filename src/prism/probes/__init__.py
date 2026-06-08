"""Active oversight probes — verifiers that RE-QUERY the producer (side-effecting),
distinct from the passive multi-lens engine. The sycophancy probes (wedge #2 v2) are
the L4 fix passive finetune could not deliver: a regressive-vs-deference call needs a
correctness reference, so the probe anchors a flip to one by re-querying the producer.
See specialist/dataset/SYCOPHANCY_RESULTS.md."""

from prism.probes.sycophancy import (
    ProbeResult,
    capitulation_probe,
    counterfactual_probe,
    run_active_sycophancy,
)

__all__ = [
    "ProbeResult",
    "capitulation_probe",
    "counterfactual_probe",
    "run_active_sycophancy",
]
