"""Deterministic film-rupture criteria and event-time localization."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable


@dataclass(frozen=True)
class RuptureConfig:
    thickness_threshold_m: float
    dwell_time_s: float = 0.0
    allow_user_trigger: bool = True
    disjoining_instability_enabled: bool = False
    strain_area_instability_enabled: bool = False
    stochastic_nucleation_enabled: bool = False

    def __post_init__(self) -> None:
        if self.thickness_threshold_m <= 0.0 or not math.isfinite(self.thickness_threshold_m):
            raise ValueError("thickness threshold must be finite and positive")
        if self.dwell_time_s < 0.0 or not math.isfinite(self.dwell_time_s):
            raise ValueError("dwell time must be finite and non-negative")


@dataclass(frozen=True)
class RuptureObservation:
    time_s: float
    min_thickness_m: float
    user_trigger: bool = False
    user_detail: str | None = None
    disjoining_pressure_pa: float | None = None
    area_rate_s_inv: float | None = None

    def __post_init__(self) -> None:
        if self.time_s < 0.0 or not math.isfinite(self.time_s):
            raise ValueError("observation time must be finite and non-negative")
        if self.min_thickness_m < 0.0 or not math.isfinite(self.min_thickness_m):
            raise ValueError("minimum film thickness must be finite and non-negative")


@dataclass(frozen=True)
class RuptureDecision:
    rupture_time_s: float
    criterion: str
    threshold_m: float | None
    detail: str
    bracket_start_s: float
    bracket_end_s: float
    interpolation_fraction: float | None
    thickness_start_m: float
    thickness_end_m: float


@dataclass(frozen=True)
class RuptureHooks:
    disjoining_instability: Callable[[RuptureObservation], bool] | None = None
    strain_area_instability: Callable[[RuptureObservation], bool] | None = None
    stochastic_nucleation: Callable[[RuptureObservation, int], bool] | None = None


class RuptureTracker:
    """Track a continuous below-threshold interval across sampled solver states.

    Thickness is assumed piecewise linear between accepted states only for event-time
    localization. The physical thinning evolution itself remains owned by the
    thin-film or transient solver.
    """

    def __init__(
        self,
        config: RuptureConfig,
        *,
        hooks: RuptureHooks | None = None,
        seed: int = 0,
        film_id: str = "film",
    ) -> None:
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.config = config
        self.hooks = hooks or RuptureHooks()
        self.previous: RuptureObservation | None = None
        self.below_since_s: float | None = None
        self.fired = False
        seed_payload = f"{seed}|{film_id}".encode("utf-8")
        self.film_seed = int(hashlib.sha256(seed_payload).hexdigest()[:16], 16)

    @staticmethod
    def _crossing_time(
        t0: float,
        h0: float,
        t1: float,
        h1: float,
        threshold: float,
    ) -> tuple[float, float]:
        if t1 == t0 or h1 == h0:
            return t1, 1.0
        fraction = (h0 - threshold) / (h0 - h1)
        fraction = min(1.0, max(0.0, fraction))
        return t0 + fraction * (t1 - t0), fraction

    def observe(self, observation: RuptureObservation) -> RuptureDecision | None:
        if self.fired:
            return None
        previous = self.previous
        if previous is not None and observation.time_s < previous.time_s:
            raise ValueError("rupture observations must be time ordered")

        cfg = self.config
        threshold = cfg.thickness_threshold_m
        candidates: list[tuple[float, int, RuptureDecision]] = []

        if previous is None:
            if observation.min_thickness_m <= threshold:
                self.below_since_s = observation.time_s
                if cfg.dwell_time_s == 0.0:
                    candidates.append((
                        observation.time_s,
                        0,
                        RuptureDecision(
                            rupture_time_s=observation.time_s,
                            criterion="THICKNESS_THRESHOLD",
                            threshold_m=threshold,
                            detail="initial accepted state is at or below the configured thickness threshold",
                            bracket_start_s=observation.time_s,
                            bracket_end_s=observation.time_s,
                            interpolation_fraction=0.0,
                            thickness_start_m=observation.min_thickness_m,
                            thickness_end_m=observation.min_thickness_m,
                        ),
                    ))
        else:
            t0, t1 = previous.time_s, observation.time_s
            h0, h1 = previous.min_thickness_m, observation.min_thickness_m
            exit_time: float | None = None
            enter_fraction: float | None = None

            if h0 > threshold and h1 <= threshold:
                enter_time, enter_fraction = self._crossing_time(t0, h0, t1, h1, threshold)
                self.below_since_s = enter_time
            elif h0 <= threshold and h1 <= threshold:
                if self.below_since_s is None:
                    self.below_since_s = t0
            elif h0 <= threshold and h1 > threshold:
                if self.below_since_s is None:
                    self.below_since_s = t0
                exit_time, _ = self._crossing_time(t0, h0, t1, h1, threshold)
            else:
                self.below_since_s = None

            if self.below_since_s is not None:
                due = self.below_since_s + cfg.dwell_time_s
                interval_end = t1 if exit_time is None else exit_time
                epsilon = 8.0 * math.ulp(max(abs(interval_end), 1.0))
                if due <= interval_end + epsilon:
                    criterion = "THICKNESS_THRESHOLD" if cfg.dwell_time_s == 0.0 else "THICKNESS_DWELL"
                    detail = (
                        "linearly localized threshold crossing from accepted thin-film states"
                        if cfg.dwell_time_s == 0.0
                        else "continuous time below thickness threshold satisfied configured dwell"
                    )
                    interpolation = enter_fraction if cfg.dwell_time_s == 0.0 else (
                        0.0 if t1 == t0 else (due - t0) / (t1 - t0)
                    )
                    candidates.append((
                        due,
                        0,
                        RuptureDecision(
                            rupture_time_s=due,
                            criterion=criterion,
                            threshold_m=threshold,
                            detail=detail,
                            bracket_start_s=t0,
                            bracket_end_s=t1,
                            interpolation_fraction=min(1.0, max(0.0, interpolation)) if interpolation is not None else None,
                            thickness_start_m=h0,
                            thickness_end_m=h1,
                        ),
                    ))
            if exit_time is not None:
                self.below_since_s = None

        if cfg.allow_user_trigger and observation.user_trigger:
            candidates.append((
                observation.time_s,
                1,
                RuptureDecision(
                    rupture_time_s=observation.time_s,
                    criterion="USER_TRIGGER",
                    threshold_m=None,
                    detail=observation.user_detail or "deterministic user-triggered rupture",
                    bracket_start_s=observation.time_s if previous is None else previous.time_s,
                    bracket_end_s=observation.time_s,
                    interpolation_fraction=None,
                    thickness_start_m=observation.min_thickness_m if previous is None else previous.min_thickness_m,
                    thickness_end_m=observation.min_thickness_m,
                ),
            ))

        if cfg.disjoining_instability_enabled and self.hooks.disjoining_instability is not None:
            if self.hooks.disjoining_instability(observation):
                candidates.append((
                    observation.time_s,
                    2,
                    RuptureDecision(
                        rupture_time_s=observation.time_s,
                        criterion="DISJOINING_INSTABILITY_HOOK",
                        threshold_m=None,
                        detail="configured disjoining-pressure instability hook fired",
                        bracket_start_s=observation.time_s if previous is None else previous.time_s,
                        bracket_end_s=observation.time_s,
                        interpolation_fraction=None,
                        thickness_start_m=observation.min_thickness_m if previous is None else previous.min_thickness_m,
                        thickness_end_m=observation.min_thickness_m,
                    ),
                ))

        if cfg.strain_area_instability_enabled and self.hooks.strain_area_instability is not None:
            if self.hooks.strain_area_instability(observation):
                candidates.append((
                    observation.time_s,
                    3,
                    RuptureDecision(
                        rupture_time_s=observation.time_s,
                        criterion="STRAIN_AREA_RATE_HOOK",
                        threshold_m=None,
                        detail="configured strain/area-rate instability hook fired",
                        bracket_start_s=observation.time_s if previous is None else previous.time_s,
                        bracket_end_s=observation.time_s,
                        interpolation_fraction=None,
                        thickness_start_m=observation.min_thickness_m if previous is None else previous.min_thickness_m,
                        thickness_end_m=observation.min_thickness_m,
                    ),
                ))

        if cfg.stochastic_nucleation_enabled and self.hooks.stochastic_nucleation is not None:
            if self.hooks.stochastic_nucleation(observation, self.film_seed):
                candidates.append((
                    observation.time_s,
                    4,
                    RuptureDecision(
                        rupture_time_s=observation.time_s,
                        criterion="SEEDED_STOCHASTIC_HOOK",
                        threshold_m=None,
                        detail="explicitly enabled seeded stochastic nucleation hook fired",
                        bracket_start_s=observation.time_s if previous is None else previous.time_s,
                        bracket_end_s=observation.time_s,
                        interpolation_fraction=None,
                        thickness_start_m=observation.min_thickness_m if previous is None else previous.min_thickness_m,
                        thickness_end_m=observation.min_thickness_m,
                    ),
                ))

        self.previous = observation
        if not candidates:
            return None
        _, _, decision = min(candidates, key=lambda item: (item[0], item[1], item[2].criterion))
        self.fired = True
        return decision
