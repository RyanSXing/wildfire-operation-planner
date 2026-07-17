from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.persistence.observed_models import (
    QuarantinedObservationModel,
    materialize_json_object,
)
from wildfireops.sources.base import SourceValidationFailure


async def write_quarantine(
    session: AsyncSession,
    failures: Sequence[SourceValidationFailure],
) -> int:
    session.add_all(
        [
            QuarantinedObservationModel(
                source_name=failure.source_name,
                source_record_id=None,
                validation_reason=failure.reason,
                raw_payload=materialize_json_object(failure.raw_payload),
            )
            for failure in failures
        ]
    )
    return len(failures)
