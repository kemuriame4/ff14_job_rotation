from __future__ import annotations

import time
from dataclasses import dataclass

from .models import Job, normalize_key_text


@dataclass
class InputEvent:
    t: float
    skill: str
    key: str = ""
    source: str = ""


class TrainingSession:
    """Records mapped skill presses during a fixed time window."""

    def __init__(self, job: Job, duration: float) -> None:
        self.job = job
        self.duration = max(0.1, float(duration))
        self.events: list[InputEvent] = []
        self._lookup = job.key_lookup()
        self._started: float | None = None
        self._stopped: float | None = None

    @property
    def running(self) -> bool:
        return self._started is not None and self._stopped is None

    @property
    def elapsed(self) -> float:
        if self._started is None:
            return 0.0
        end = self._stopped if self._stopped is not None else time.perf_counter()
        return max(0.0, min(self.duration, end - self._started))

    def start(self) -> None:
        self.events = []
        self._started = time.perf_counter()
        self._stopped = None

    def stop(self) -> float:
        if self._started is not None and self._stopped is None:
            self._stopped = time.perf_counter()
        return self.elapsed

    def add_key(self, canonical: str, source: str = "app") -> InputEvent | None:
        if not self.running:
            return None
        key = normalize_key_text(canonical)
        skill = self._lookup.get(key)
        if skill is None:
            return None
        return self._push(skill.name, key, source)

    def add_skill(
        self, skill_name: str, source: str = "click", key: str | None = None
    ) -> InputEvent | None:
        if not self.running:
            return None
        skill = self.job.skill(skill_name)
        if skill is None:
            return None
        key_text = skill.key if key is None else key
        return self._push(skill_name, key_text, source)

    def _push(self, skill: str, key: str, source: str) -> InputEvent | None:
        t = self.elapsed
        if self.events:
            last = self.events[-1]
            if last.skill == skill and t - last.t < 0.09:
                # Same press captured twice (global hook + in-app event).
                return None
        event = InputEvent(t=t, skill=skill, key=key, source=source)
        self.events.append(event)
        return event
