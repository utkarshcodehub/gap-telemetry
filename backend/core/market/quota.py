"""
A hard monthly request cap for metered external APIs.

JSearch's free tier is 200 requests/month and the API exposes **no quota headers
at all** — a response tells you nothing about how much allowance is left. So
nothing except this ledger stands between a retry loop and a blown monthly cap,
and once the cap is gone it is gone for the rest of the calendar month.

Three properties make the cap actually hold:

1. **Spend is recorded BEFORE the request is issued.** Pessimistic on purpose. A
   request that times out or 500s may still have been metered upstream, and we
   cannot tell. Over-counting costs us a few requests; under-counting silently
   exceeds the cap.

2. **The file is re-read on every spend.** A second process, a retry loop, or a
   rerun after a crash all see the current total rather than a stale in-memory
   copy. This is what makes "even if something retries in a loop" true.

3. **Writes are atomic.** Temp file plus `os.replace`, so a crash mid-write
   cannot leave a truncated ledger that reads as zero usage.

The ledger lives under `backend/data/`, which is gitignored: it is per-machine
usage state, not shared project data. A fresh clone therefore starts at zero —
if more than one person ever runs the feed, the cap is per-machine and the real
upstream total is the sum. Keep the feed on one machine.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

#: Free tier is 200/month. The feed is capped below that so there is always
#: headroom for diagnostics, a retry, or a mistake.
DEFAULT_MONTHLY_CAP = 190


class QuotaExhausted(RuntimeError):
    """Raised instead of issuing a request that would exceed the monthly cap."""


class QuotaLedger:
    def __init__(self, path: Path | str, monthly_cap: int = DEFAULT_MONTHLY_CAP):
        self.path = Path(path)
        self.monthly_cap = monthly_cap

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def month_key(when: datetime | None = None) -> str:
        when = when or datetime.now(timezone.utc)
        return f"{when.year:04d}-{when.month:02d}"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"monthly_cap": self.monthly_cap, "months": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt ledger must NOT read as "zero used" -- that would hand a
            # fresh 190 requests to whatever just crashed. Fail loudly instead.
            raise QuotaExhausted(
                f"quota ledger at {self.path} is unreadable; refusing to spend. "
                "Inspect or delete it deliberately."
            )
        data.setdefault("months", {})
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _month(self, data: dict, month: str) -> dict:
        return data["months"].setdefault(
            month, {"requests": 0, "results": 0, "new_rows": 0, "runs": []}
        )

    # ------------------------------------------------------------------ reads

    def used(self, month: str | None = None) -> int:
        month = month or self.month_key()
        return self._load()["months"].get(month, {}).get("requests", 0)

    def remaining(self, month: str | None = None) -> int:
        return max(0, self.monthly_cap - self.used(month))

    def summary(self, month: str | None = None) -> dict:
        month = month or self.month_key()
        m = self._load()["months"].get(
            month, {"requests": 0, "results": 0, "new_rows": 0, "runs": []}
        )
        return {
            "month": month,
            "cap": self.monthly_cap,
            "used": m["requests"],
            "remaining": max(0, self.monthly_cap - m["requests"]),
            "results": m["results"],
            "new_rows": m["new_rows"],
            "runs": len(m["runs"]),
        }

    # ----------------------------------------------------------------- writes

    def spend(self, n: int = 1, *, note: str = "", month: str | None = None) -> int:
        """Reserve `n` requests, or raise QuotaExhausted. Returns remaining after.

        Call this immediately BEFORE issuing the request(s), never after.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        month = month or self.month_key()
        data = self._load()           # re-read: a retry loop must see the truth
        m = self._month(data, month)
        if m["requests"] + n > self.monthly_cap:
            raise QuotaExhausted(
                f"{month}: {m['requests']}/{self.monthly_cap} requests already used; "
                f"cannot spend {n} more. Cap reached — wait for the next calendar "
                f"month or raise monthly_cap deliberately."
            )
        m["requests"] += n
        if note:
            m["runs"].append({
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "spent": n,
                "note": note,
            })
        self._save(data)
        return self.monthly_cap - m["requests"]

    def record_yield(self, *, results: int, new_rows: int,
                     month: str | None = None) -> None:
        """Record what the spent requests actually produced. Never affects the cap."""
        month = month or self.month_key()
        data = self._load()
        m = self._month(data, month)
        m["results"] += results
        m["new_rows"] += new_rows
        self._save(data)
