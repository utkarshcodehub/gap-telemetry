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

import calendar
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

#: The provider's actual allowance is 200 per billing period. The feed caps
#: itself below that so there is always headroom for diagnostics, a retry, or a
#: mistake -- the allowance cannot be topped up mid-period.
PROVIDER_ALLOWANCE = 200
DEFAULT_MONTHLY_CAP = 190

#: Day of month the provider's allowance resets. OpenWeb Ninja bills on a rolling
#: period anchored to the signup date, NOT the calendar month -- this account
#: resets on the 2nd (observed: "resetting Nov 2, 2026"). Keying the ledger by
#: calendar month would therefore mis-account across every boundary: usage on the
#: 1st belongs to the period that began the previous month.
DEFAULT_RESET_DAY = 2


class QuotaExhausted(RuntimeError):
    """Raised instead of issuing a request that would exceed the monthly cap."""


class QuotaLedger:
    def __init__(
        self,
        path: Path | str,
        monthly_cap: int = DEFAULT_MONTHLY_CAP,
        reset_day: int = DEFAULT_RESET_DAY,
    ):
        if not 1 <= reset_day <= 28:
            # Above 28 a period would vanish in February; the provider would not
            # do that, and allowing it here would hide the bug until a leap year.
            raise ValueError("reset_day must be 1..28")
        self.path = Path(path)
        self.monthly_cap = monthly_cap
        self.reset_day = reset_day

    # ---------------------------------------------------------------- helpers

    def period_key(self, when: datetime | None = None) -> str:
        """Identify the billing period containing `when`, by its start date.

        Periods run reset_day -> reset_day, so with reset_day=2 the period
        "2026-10-02" covers 2026-10-02 through 2026-11-01 inclusive. A request on
        1 November belongs to the period that began 2 October, which is exactly
        the case a calendar-month key gets wrong.
        """
        when = when or datetime.now(timezone.utc)
        year, month = when.year, when.month
        if when.day < self.reset_day:
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        day = min(self.reset_day, calendar.monthrange(year, month)[1])
        return f"{year:04d}-{month:02d}-{day:02d}"

    #: Deprecated alias. Kept only so an old call site fails loudly rather than
    #: silently keying by calendar month again.
    def month_key(self, when: datetime | None = None) -> str:  # pragma: no cover
        raise AttributeError(
            "month_key() was removed: the provider resets on a rolling period "
            "anchored to reset_day, not the calendar month. Use period_key()."
        )

    def _load(self) -> dict:
        if not self.path.exists():
            return {"cap": self.monthly_cap, "reset_day": self.reset_day,
                    "provider_allowance": PROVIDER_ALLOWANCE, "periods": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt ledger must NOT read as "zero used" -- that would hand a
            # fresh 190 requests to whatever just crashed. Fail loudly instead.
            raise QuotaExhausted(
                f"quota ledger at {self.path} is unreadable; refusing to spend. "
                "Inspect or delete it deliberately."
            )
        data.setdefault("periods", {})
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

    def _period(self, data: dict, period: str) -> dict:
        return data["periods"].setdefault(
            period, {"requests": 0, "results": 0, "new_rows": 0, "runs": []}
        )

    # ------------------------------------------------------------------ reads

    def used(self, period: str | None = None) -> int:
        period = period or self.period_key()
        return self._load()["periods"].get(period, {}).get("requests", 0)

    def remaining(self, period: str | None = None) -> int:
        return max(0, self.monthly_cap - self.used(period))

    def summary(self, period: str | None = None) -> dict:
        period = period or self.period_key()
        m = self._load()["periods"].get(
            period, {"requests": 0, "results": 0, "new_rows": 0, "runs": []}
        )
        return {
            "period": period,
            "cap": self.monthly_cap,
            "used": m["requests"],
            "remaining": max(0, self.monthly_cap - m["requests"]),
            "results": m["results"],
            "new_rows": m["new_rows"],
            "runs": len(m["runs"]),
        }

    # ----------------------------------------------------------------- writes

    def spend(self, n: int = 1, *, note: str = "", period: str | None = None) -> int:
        """Reserve `n` requests, or raise QuotaExhausted. Returns remaining after.

        Call this immediately BEFORE issuing the request(s), never after.
        """
        if n <= 0:
            raise ValueError("n must be positive")
        period = period or self.period_key()
        data = self._load()           # re-read: a retry loop must see the truth
        m = self._period(data, period)
        if m["requests"] + n > self.monthly_cap:
            raise QuotaExhausted(
                f"{period}: {m['requests']}/{self.monthly_cap} requests already used; "
                f"cannot spend {n} more. Cap reached — wait for the next billing "
                f"period (resets on day {self.reset_day}) or raise monthly_cap "
                f"deliberately."
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
                     period: str | None = None) -> None:
        """Record what the spent requests actually produced. Never affects the cap."""
        period = period or self.period_key()
        data = self._load()
        m = self._period(data, period)
        m["results"] += results
        m["new_rows"] += new_rows
        self._save(data)
