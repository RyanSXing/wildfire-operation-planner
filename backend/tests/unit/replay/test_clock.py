from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from wildfireops.replay.clock import ReplayClock


def test_clock_advance_and_reset_are_deterministic() -> None:
    start = datetime(2024, 7, 24, 18, tzinfo=UTC)
    clock = ReplayClock(start)

    assert clock.current_time == start
    assert clock.advance(timedelta(minutes=12)) == datetime(
        2024,
        7,
        24,
        18,
        12,
        tzinfo=UTC,
    )
    assert clock.current_time == datetime(2024, 7, 24, 18, 12, tzinfo=UTC)
    assert clock.reset() == start
    assert clock.advance(timedelta(minutes=12)) == datetime(
        2024,
        7,
        24,
        18,
        12,
        tzinfo=UTC,
    )


@pytest.mark.parametrize(
    "start_at",
    [
        datetime(2024, 7, 24, 18),
        datetime(
            2024,
            7,
            24,
            20,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    ],
)
def test_clock_requires_a_strict_utc_start(start_at: datetime) -> None:
    with pytest.raises(ValueError, match="^start_at must be UTC$"):
        ReplayClock(start_at)


@pytest.mark.parametrize(
    "delta",
    [
        timedelta(microseconds=-1),
        float("nan"),
        float("inf"),
        float("-inf"),
        1,
        None,
    ],
)
def test_clock_rejects_invalid_movement_without_changing_time(delta: Any) -> None:
    start = datetime(2024, 7, 24, 18, tzinfo=UTC)
    clock = ReplayClock(start)

    with pytest.raises(
        ValueError,
        match="^delta must be a finite nonnegative timedelta$",
    ):
        clock.advance(delta)

    assert clock.current_time == start


def test_clock_rejects_overflow_without_changing_time() -> None:
    start = datetime(2024, 7, 24, 18, tzinfo=UTC)
    clock = ReplayClock(start)

    with pytest.raises(ValueError, match="^delta moves time outside supported range$"):
        clock.advance(timedelta.max)

    assert clock.current_time == start
