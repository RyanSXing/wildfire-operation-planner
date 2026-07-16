from datetime import datetime

from wildfireops.api.schemas.incidents import ApiModel, Freshness


class SourceStatusResponse(ApiModel):
    source_name: str
    last_attempted_at: datetime
    last_success_at: datetime | None
    next_retry_at: datetime | None
    freshness: Freshness
    accepted_count: int
    deduplicated_count: int
    quarantined_count: int
    last_error_code: str | None


class SourceStatusListResponse(ApiModel):
    items: tuple[SourceStatusResponse, ...]
