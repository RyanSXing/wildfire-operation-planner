from wildfireops.api.schemas.sources import SourceStatusResponse
from wildfireops.application.read_models import SourceStatusReadModel


def source_status(model: SourceStatusReadModel) -> SourceStatusResponse:
    return SourceStatusResponse(
        source_name=model.source_name,
        last_attempted_at=model.last_attempted_at,
        last_success_at=model.last_success_at,
        next_retry_at=model.next_retry_at,
        freshness=model.freshness,
        accepted_count=model.accepted_count,
        deduplicated_count=model.deduplicated_count,
        quarantined_count=model.quarantined_count,
        last_error_code=model.last_error_code,
    )
