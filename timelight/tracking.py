"""Sampling logic independent of Windows and the GUI.

Only observed, short continuous intervals are recorded. Opening the application
never backfills earlier uptime. Sleep, a stopped sampler, and clock adjustments
break continuity, preventing hours from being attributed to a stale foreground.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    wall: float
    awake: float
    idle: float
    locked: bool
    app_key: str = ""
    app_name: str = ""
    exe_path: str = ""


class Tracker:
    MAX_GAP_SECONDS = 30.0
    CLOCK_TOLERANCE_SECONDS = 0.25

    def __init__(self, store, idle_seconds: float = 300):
        self.store = store
        self.idle_seconds = idle_seconds
        self._previous: Sample | None = None
        self._previous_paused = False
        self._recorded_until = getattr(store, "last_recorded", None)
        self.status = "unknown"

    @property
    def idle_seconds(self) -> float:
        return self._idle_seconds

    @idle_seconds.setter
    def idle_seconds(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("空闲阈值必须大于零")
        self._idle_seconds = value

    def reset(self) -> None:
        """Discard continuity after a sampling failure or a deliberate stop."""
        self._previous = None
        self.status = "unknown"

    def _state(self, sample: Sample, paused: bool) -> str:
        if paused:
            return "paused"
        if sample.locked:
            return "locked"
        if sample.idle >= self.idle_seconds:
            return "idle"
        return "active" if sample.app_key else "unknown"

    def tick(self, sample: Sample, paused: bool = False) -> None:
        if any(not math.isfinite(value) for value in (sample.wall, sample.awake, sample.idle)):
            self.reset()
            raise ValueError("采样时钟必须是有限数值")
        if sample.awake < 0 or sample.idle < 0:
            self.reset()
            raise ValueError("采样时长不能为负数")
        previous, was_paused = self._previous, self._previous_paused
        self._previous, self._previous_paused = sample, bool(paused)
        self.status = self._state(sample, paused)
        if previous is None:
            return
        # A manually adjusted clock can move samples back into saved history.
        # Wait until it catches up, including after restarting the application.
        if self._recorded_until is not None and previous.wall < self._recorded_until:
            return
        wall_delta = sample.wall - previous.wall
        awake_delta = sample.awake - previous.awake
        if (wall_delta <= 0 or awake_delta <= 0
                or max(wall_delta, awake_delta) > self.MAX_GAP_SECONDS
                or abs(wall_delta - awake_delta) > self.CLOCK_TOLERANCE_SECONDS):
            return

        # The awake clock verifies continuity. Within sampling tolerance, wall
        # boundaries give contiguous intervals instead of a new row each second
        # due solely to microsecond differences between the two clock reads.
        duration = wall_delta
        start = previous.wall
        if was_paused or previous.locked:
            self.store.add_interval(start, start + duration, "paused" if was_paused else "locked")
            self._recorded_until = start + duration
            return

        def record_segment(offset: float, length: float, initial_idle: float) -> None:
            if length <= 0:
                return
            active_length = min(length, max(0.0, self.idle_seconds - initial_idle))
            if active_length > 0:
                self.store.add_interval(
                    start + offset, start + offset + active_length,
                    "active" if previous.app_key else "unknown",
                    previous.app_key, previous.app_name, previous.exe_path,
                )
            if active_length < length:
                self.store.add_interval(start + offset + active_length, start + offset + length, "idle")

        # A reset in the idle timer places the most recent input within this
        # interval. Preserve any idle portion before that input.
        if sample.idle < previous.idle + duration - 0.05 and sample.idle < duration:
            input_offset = duration - sample.idle
            record_segment(0.0, input_offset, previous.idle)
            record_segment(input_offset, sample.idle, 0.0)
        else:
            record_segment(0.0, duration, previous.idle)
        self._recorded_until = start + duration
