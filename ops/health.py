from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    is_healthy: bool = True
    last_poll_ts: float = field(default_factory=time.time)
    last_error: str = ""
    cycle_count: int = 0
    error_count: int = 0


class HealthChecker:
    def __init__(self, stall_threshold_sec: int = 120) -> None:
        self._stall_threshold = stall_threshold_sec
        self._status = HealthStatus()

    def on_cycle_start(self) -> None:
        self._status.cycle_count += 1
        self._status.last_poll_ts = time.time()

    def on_error(self, msg: str) -> None:
        self._status.error_count += 1
        self._status.last_error = msg
        self._status.is_healthy = False

    def on_success(self) -> None:
        self._status.is_healthy = True
        self._status.last_error = ""

    def is_stalled(self) -> bool:
        elapsed = time.time() - self._status.last_poll_ts
        return elapsed > self._stall_threshold

    @property
    def status(self) -> HealthStatus:
        return self._status

    def summary(self) -> str:
        s = self._status
        elapsed = time.time() - s.last_poll_ts
        return (
            f"cycles={s.cycle_count} errors={s.error_count} "
            f"last_poll={elapsed:.0f}s ago healthy={s.is_healthy}"
        )
