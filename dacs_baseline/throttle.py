from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Throttle:
    """User-controlled pacing for DACS-friendly scanning."""

    delay_seconds: float = 2.0
    batch_size: int = 0  # 0 disables batch pauses
    batch_pause_seconds: float = 30.0

    def after_item(self, scanned_count: int) -> None:
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        if self.batch_size > 0 and scanned_count > 0 and scanned_count % self.batch_size == 0:
            if self.batch_pause_seconds > 0:
                print(
                    f"[throttle] batch {scanned_count} complete — "
                    f"pausing {self.batch_pause_seconds:.0f}s"
                )
                time.sleep(self.batch_pause_seconds)
