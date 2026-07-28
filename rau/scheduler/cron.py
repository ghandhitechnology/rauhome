"""Small five-field POSIX cron parser with timezone-aware matching."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import FrozenSet
from zoneinfo import ZoneInfo


class CronError(ValueError):
    pass


def _field(text: str, minimum: int, maximum: int, *, dow: bool = False) -> FrozenSet[int]:
    values: set[int] = set()
    raw = text.strip()
    if not raw:
        raise CronError("empty cron field")
    for part in raw.split(","):
        base, slash, step_text = part.partition("/")
        try:
            step = int(step_text) if slash else 1
        except ValueError as exc:
            raise CronError(f"invalid cron step: {part}") from exc
        if step <= 0:
            raise CronError("cron step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            left, right = base.split("-", 1)
            try:
                start, end = int(left), int(right)
            except ValueError as exc:
                raise CronError(f"invalid cron range: {part}") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronError(f"invalid cron value: {part}") from exc
        if dow:
            # POSIX spells Sunday as 0 or 7. Expand on the raw numbers so a
            # range ending in 7 (5-7 = Fri-Sun) still spans the week, then fold
            # 7 back to 0 — mapping first turns 5-7 into a descending range.
            if start < minimum or start > 7 or end < minimum or end > 7:
                raise CronError(f"cron value outside {minimum}-7: {part}")
            if start > end:
                raise CronError(f"descending cron range is unsupported: {part}")
            values.update(0 if value == 7 else value for value in range(start, end + 1, step))
            continue
        if start < minimum or start > maximum or end < minimum or end > maximum:
            raise CronError(f"cron value outside {minimum}-{maximum}: {part}")
        if start > end:
            raise CronError(f"descending cron range is unsupported: {part}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class CronSpec:
    expression: str
    minutes: FrozenSet[int]
    hours: FrozenSet[int]
    days: FrozenSet[int]
    months: FrozenSet[int]
    weekdays: FrozenSet[int]
    day_wildcard: bool
    weekday_wildcard: bool

    @classmethod
    def parse(cls, expression: str) -> "CronSpec":
        parts = str(expression or "").split()
        if len(parts) != 5:
            raise CronError("cron expression must contain five fields")
        minute, hour, day, month, weekday = parts
        return cls(
            expression=" ".join(parts),
            minutes=_field(minute, 0, 59),
            hours=_field(hour, 0, 23),
            days=_field(day, 1, 31),
            months=_field(month, 1, 12),
            weekdays=_field(weekday, 0, 6, dow=True),
            day_wildcard=day == "*",
            weekday_wildcard=weekday == "*",
        )

    def matches(self, local: datetime) -> bool:
        if local.minute not in self.minutes or local.hour not in self.hours:
            return False
        return self._calendar_matches(local)

    def _calendar_matches(self, local: datetime) -> bool:
        """Month/day-of-month/day-of-week fields, with POSIX dom/dow OR."""
        if local.month not in self.months:
            return False
        day_match = local.day in self.days
        posix_weekday = (local.weekday() + 1) % 7
        weekday_match = posix_weekday in self.weekdays
        if self.day_wildcard:
            return weekday_match
        if self.weekday_wildcard:
            return day_match
        # POSIX cron treats restricted day-of-month/day-of-week as OR.
        return day_match or weekday_match

    def next_after(
        self,
        after_timestamp: float,
        timezone_name: str,
        *,
        max_minutes: int = 5 * 366 * 24 * 60,
    ) -> float:
        zone = ZoneInfo(timezone_name)
        minute = int(after_timestamp // 60) * 60 + 60
        horizon = minute + max_minutes * 60
        while minute < horizon:
            local = datetime.fromtimestamp(minute, tz=timezone.utc).astimezone(zone)
            if self.matches(local):
                return float(minute)
            # Sparse expressions must not minute-step through spans that
            # cannot match (Feb 29 would otherwise scan ~4 years of minutes);
            # jump to the next boundary that could.
            step = 60
            if local.month not in self.months:
                year = local.year + (1 if local.month == 12 else 0)
                month = 1 if local.month == 12 else local.month + 1
                step = int(datetime(year, month, 1, tzinfo=zone).timestamp()) - minute
            elif not self._calendar_matches(local):
                step = (
                    int(
                        (local + timedelta(days=1))
                        .replace(hour=0, minute=0, second=0, microsecond=0)
                        .timestamp()
                    )
                    - minute
                )
            elif local.hour not in self.hours:
                step = (
                    int(
                        (local + timedelta(hours=1))
                        .replace(minute=0, second=0, microsecond=0)
                        .timestamp()
                    )
                    - minute
                )
            minute += max(60, step)
        raise CronError("no cron occurrence found within five years")


def nominal_key(timestamp: float, timezone_name: str) -> str:
    """Local wall-minute identity; repeated DST minutes intentionally collide."""
    local = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(
        ZoneInfo(timezone_name)
    )
    return f"{timezone_name}:{local.strftime('%Y-%m-%dT%H:%M')}"
