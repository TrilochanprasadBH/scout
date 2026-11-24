"""Statistics the reports need.

Only what is used. `ragkit` stage 07 carries the full argument for why these exist; this is
the same arithmetic, copied rather than imported so that each project stands alone.
"""

from __future__ import annotations

import math


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion.

    The normal approximation gives a zero-width interval at 0% and 100%, which is exactly
    where a small eval set spends its time. Wilson does not.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denominator = 1 + (z * z) / n
    centre = p + (z * z) / (2 * n)
    margin = z * math.sqrt((p * (1 - p) / n) + (z * z) / (4 * n * n))
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


def mcnemar_exact_p(n01: int, n10: int) -> float:
    """Two-sided exact McNemar p-value for paired results.

    `n01` counts questions where the first configuration succeeded and the second failed.
    Questions where both agree carry no information about which is better, so the test only
    looks at the discordant pairs. With 16 development questions this is the only paired
    test worth running: the chi-squared version assumes counts this project does not have.
    """
    discordant = n01 + n10
    if discordant == 0:
        return 1.0
    k = max(n01, n10)
    tail = sum(math.comb(discordant, i) for i in range(k, discordant + 1)) / (2**discordant)
    return min(1.0, 2 * tail)


def discordant_needed(pairs: int, alpha: float = 0.05) -> int:
    """How many one-directional discordant pairs are needed for significance.

    With few questions, a paired test cannot reach `p < 0.05` however good the change is.
    Reporting the floor next to a p-value stops a promising direction from being described
    as a result: with 13 questions nothing below six discordant pairs can be significant,
    so "2 wins, 0 losses, p = 0.50" is a direction, not evidence.
    """
    for count in range(1, pairs + 1):
        if mcnemar_exact_p(count, 0) < alpha:
            return count
    return pairs + 1


def standard_error(left: list[float], right: list[float]) -> float:
    """Standard error of the difference in means, unpaired.

    Correct when the two arms score different question sets, and reported only in that case.
    Every comparison in this project is paired, so this exists for the paired numbers'
    sanity check rather than for a claim.
    """
    def variance(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    return math.sqrt(variance(left) / max(1, len(left)) + variance(right) / max(1, len(right)))
