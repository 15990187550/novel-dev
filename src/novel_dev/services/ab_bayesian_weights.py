from __future__ import annotations
from typing import Optional


DEFAULT_WEIGHTS = {"critic": 0.5, "hook": 0.3, "thrill": 0.2}


class BayesianWeightUpdater:
    """Dirichlet posterior over (critic, hook, thrill) weights.

    Updates only when sample_count crosses a multiple of update_interval.
    Constraints: any weight must stay within ±max_drift of the prior.
    """

    def __init__(
        self,
        prior: Optional[dict] = None,
        update_interval: int = 50,
        max_drift: float = 0.2,
        random_seed: int = 42,
    ):
        self.prior = prior or DEFAULT_WEIGHTS
        self.update_interval = update_interval
        self.max_drift = max_drift
        self._last_update_at = 0

    def update(
        self,
        sample_count: int,
        observed: Optional[dict] = None,
    ) -> dict:
        if sample_count < self.update_interval:
            return DEFAULT_WEIGHTS
        if (sample_count - self._last_update_at) < self.update_interval:
            return DEFAULT_WEIGHTS
        if observed is None:
            return DEFAULT_WEIGHTS

        total = sum(max(observed.get(k, 0.0), 0.0) for k in self.prior)
        if total <= 0:
            return DEFAULT_WEIGHTS

        raw = {k: max(observed.get(k, 0.0), 0.0) / total for k in self.prior}

        clipped = {}
        for k, default in self.prior.items():
            lo = max(0.0, default - self.max_drift)
            hi = default + self.max_drift
            clipped[k] = max(lo, min(hi, raw[k]))

        s = sum(clipped.values())
        normalized = {k: v / s for k, v in clipped.items()}

        self._last_update_at = sample_count
        return normalized