"""External coding-judgment benchmarks for prism (F-01 sub-build 3).

``codejudgebench`` loads the HF ``mattymchen/codejudgebench`` pairwise dataset (arXiv:2507.10535,
Apache-2.0) into ``CJBItem``s; ``harness`` runs prism's single-artifact ``verify`` on each (chosen,
rejected) pair, reduces the two verdicts to a preference via ``calibrate.pairwise_prefer``, and
summarizes accuracy + position-consistency + tie-rate with Wilson CIs.
"""

from __future__ import annotations
