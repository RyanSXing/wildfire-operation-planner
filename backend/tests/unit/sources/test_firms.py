from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from wildfireops.domain.observations import NormalizedObservation
from wildfireops.sources.firms import FirmsAdapter
from wildfireops.sources.http import RetryPolicy, SourceUnavailable


FIXTURES = Path(__file__).parents[2] / "fixtures"
REQUEST_URL = "https://sources.invalid/firms.csv"


async def no_sleep(_: float) -> None:
    pass


def csv_transport(csv_payload: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv_payload, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_firms_adapter_normalizes_fixture_with_stable_identity() -> None:
    csv_payload = (FIXTURES / "firms_sample.csv").read_text()

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        adapter = FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
        )
        batch = await adapter.fetch()

    assert batch.failures == ()
    assert len(batch.observations) == 2
    observations = [
        observation
        for observation in batch.observations
        if isinstance(observation, NormalizedObservation)
    ]
    assert len(observations) == 2
    assert [observation.observed_at for observation in observations] == [
        datetime(2024, 7, 24, 18, 12, tzinfo=UTC),
        datetime(2024, 7, 24, 18, 18, tzinfo=UTC),
    ]
    assert [observation.confidence for observation in observations] == [
        0.95,
        0.75,
    ]
    assert [observation.source_record_id for observation in observations] == [
        "df5b3b3964ca41912c0d6c6e9c9153bf4adec9212c4e009efac2ea038adb38a3",
        "91c40275d5426f2bd16fcb1c163b5f657e7613b282e7efc736e031d8888ec894",
    ]
    assert observations[0].raw_payload == {
        "latitude": "39.805",
        "longitude": "-121.612",
        "bright_ti4": "341.6",
        "confidence": "h",
        "acq_date": "2024-07-24",
        "acq_time": "1812",
        "satellite": "N20",
        "instrument": "VIIRS",
    }


@pytest.mark.asyncio
async def test_firms_adapter_quarantines_bad_row_without_dropping_valid_row() -> None:
    csv_payload = """\
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
not-a-latitude,-121.612,341.6,h,2024-07-24,1812,N20,VIIRS
39.807,-121.609,335.2,n,2024-07-24,1818,N20,VIIRS
"""

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            sleep=no_sleep,
        ).fetch()

    assert len(batch.observations) == 1
    assert batch.observations[0].latitude == 39.807
    assert len(batch.failures) == 1
    assert batch.failures[0].source_name == "nasa_firms"
    assert batch.failures[0].reason == "invalid FIRMS row: latitude must be a number"
    assert batch.failures[0].raw_payload["latitude"] == "not-a-latitude"


@pytest.mark.asyncio
async def test_firms_identity_rounds_coordinates_to_five_decimal_places() -> None:
    csv_payload = """\
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
39.805001,-121.612001,341.6,h,2024-07-24,1812,N20,VIIRS
39.805002,-121.612002,341.6,h,2024-07-24,1812,N20,VIIRS
"""

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    assert (
        batch.observations[0].source_record_id == batch.observations[1].source_record_id
    )


@pytest.mark.asyncio
async def test_firms_identity_changes_when_a_source_field_changes() -> None:
    csv_payload = """\
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
39.805,-121.612,341.6,h,2024-07-24,1812,N20,VIIRS
39.805,-121.612,341.6,h,2024-07-24,1812,N21,VIIRS
"""

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    assert (
        batch.observations[0].source_record_id != batch.observations[1].source_record_id
    )


@pytest.mark.asyncio
async def test_firms_identity_canonicalizes_source_field_case_and_whitespace() -> None:
    csv_payload = """\
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
39.805,-121.612,341.6,h,2024-07-24,1812,N20,VIIRS
39.805,-121.612,341.6,h,2024-07-24,1812," n20 "," viirs "
"""

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            sleep=no_sleep,
        ).fetch()

    assert batch.failures == ()
    assert (
        batch.observations[0].source_record_id == batch.observations[1].source_record_id
    )
    assert batch.observations[1].raw_payload["satellite"] == " n20 "
    assert batch.observations[1].raw_payload["instrument"] == " viirs "


@pytest.mark.asyncio
async def test_firms_adapter_retries_transient_response() -> None:
    csv_payload = (FIXTURES / "firms_sample.csv").read_text()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text=csv_payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            policy=RetryPolicy(max_attempts=2),
            sleep=no_sleep,
        ).fetch()

    assert attempts == 2
    assert len(batch.observations) == 2


@pytest.mark.asyncio
async def test_firms_adapter_exhaustion_does_not_expose_map_key() -> None:
    secret = "firms-secret-map-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=secret, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FirmsAdapter(
            client,
            client.build_request("GET", f"{REQUEST_URL}?MAP_KEY={secret}"),
            policy=RetryPolicy(max_attempts=1),
            sleep=no_sleep,
        )
        with pytest.raises(SourceUnavailable) as caught:
            await adapter.fetch()

    assert str(caught.value) == ("nasa_firms unavailable after 1 attempt (status 503)")
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


@pytest.mark.asyncio
async def test_firms_adapter_quarantines_surplus_columns_and_continues() -> None:
    csv_payload = """\
latitude,longitude,bright_ti4,confidence,acq_date,acq_time,satellite,instrument
39.805,-121.612,341.6,h,2024-07-24,1812,N20,VIIRS,unexpected
39.807,-121.609,335.2,n,2024-07-24,1818,N20,VIIRS
"""

    async with httpx.AsyncClient(transport=csv_transport(csv_payload)) as client:
        batch = await FirmsAdapter(
            client,
            client.build_request("GET", REQUEST_URL),
            sleep=no_sleep,
        ).fetch()

    assert len(batch.observations) == 1
    assert batch.observations[0].latitude == 39.807
    assert len(batch.failures) == 1
    assert batch.failures[0].reason == ("invalid FIRMS row: row has unexpected columns")
    assert batch.failures[0].raw_payload["_extra_columns"] == ("unexpected",)
