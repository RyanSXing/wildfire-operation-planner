from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wildfireops.domain.observations import SourceObservation
from wildfireops.persistence.observed_models import SourceObservationModel


@dataclass(frozen=True, slots=True)
class IngestStats:
    inserted: int
    deduplicated: int


class ObservationRepository:
    async def upsert_many(
        self,
        session: AsyncSession,
        observations: Sequence[SourceObservation],
    ) -> IngestStats:
        identities = {
            (item.source_name, item.source_record_id) for item in observations
        }
        inserted = 0
        for source_name, source_record_id in sorted(identities):
            record = next(
                value
                for value in observations
                if value.source_name == source_name
                and value.source_record_id == source_record_id
            )
            statement = (
                insert(SourceObservationModel)
                .values(SourceObservationModel.from_domain(record))
                .on_conflict_do_nothing(
                    index_elements=["source_name", "source_record_id"]
                )
                .returning(SourceObservationModel.id)
            )
            result = await session.execute(statement)
            inserted += int(result.scalar_one_or_none() is not None)

        return IngestStats(
            inserted=inserted,
            deduplicated=len(observations) - inserted,
        )
