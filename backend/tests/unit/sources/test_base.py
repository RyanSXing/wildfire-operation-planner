from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from wildfireops.sources.base import SourceBatch


def test_source_batch_preserves_two_argument_construction() -> None:
    batch = SourceBatch((), ())

    assert batch.reference_at is None


def test_source_batch_reference_is_immutable() -> None:
    reference_at = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
    batch = SourceBatch((), (), reference_at=reference_at)

    assert batch.reference_at is reference_at
    with pytest.raises(FrozenInstanceError):
        batch.reference_at = datetime(2024, 7, 24, 19, tzinfo=UTC)  # type: ignore[misc]


@pytest.mark.parametrize(
    "reference_at",
    (
        datetime(2024, 7, 24, 18, 30),
        datetime(
            2024,
            7,
            24,
            14,
            30,
            tzinfo=timezone(-timedelta(hours=4)),
        ),
    ),
)
def test_source_batch_reference_requires_exact_utc(reference_at: datetime) -> None:
    with pytest.raises(ValueError, match="reference_at must be UTC"):
        SourceBatch((), (), reference_at=reference_at)
