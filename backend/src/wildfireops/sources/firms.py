import asyncio
import csv
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite

import httpx

from wildfireops.domain.observations import (
    FrozenJsonObject,
    NormalizedObservation,
    freeze_json_object,
)
from wildfireops.sources.base import (
    SourceBatch,
    SourceValidationFailure,
)
from wildfireops.sources.http import (
    RetryPolicy,
    Sleep,
    fetch_with_retry,
)


_CONFIDENCE = {
    "l": 0.25,
    "n": 0.75,
    "h": 0.95,
}


class FirmsAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        request: httpx.Request,
        *,
        policy: RetryPolicy = RetryPolicy(),
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client = client
        self._request = request
        self._policy = policy
        self._sleep = sleep

    @property
    def source_name(self) -> str:
        return "nasa_firms"

    async def fetch(self) -> SourceBatch:
        response = await fetch_with_retry(
            self._client,
            self._request,
            self._policy,
            sleep=self._sleep,
            source_name=self.source_name,
        )
        observations: list[NormalizedObservation] = []
        failures: list[SourceValidationFailure] = []
        physical_records = response.text.splitlines()
        if not physical_records:
            return SourceBatch((), ())

        try:
            fieldnames = next(csv.reader([physical_records[0]], strict=True))
        except csv.Error:
            return SourceBatch(
                (),
                (
                    SourceValidationFailure(
                        source_name=self.source_name,
                        reason="invalid FIRMS row: CSV record is malformed",
                        raw_payload=freeze_json_object(
                            {"raw_record": physical_records[0]}
                        ),
                    ),
                ),
            )

        for raw_record in physical_records[1:]:
            if not raw_record:
                continue
            try:
                values = next(csv.reader([raw_record], strict=True))
            except csv.Error:
                failures.append(
                    SourceValidationFailure(
                        source_name=self.source_name,
                        reason="invalid FIRMS row: CSV record is malformed",
                        raw_payload=freeze_json_object({"raw_record": raw_record}),
                    )
                )
                continue

            raw_payload_data: dict[str, object] = {
                fieldname: values[index] if index < len(values) else None
                for index, fieldname in enumerate(fieldnames)
            }
            extra_columns = values[len(fieldnames) :]
            if extra_columns:
                raw_payload_data["_extra_columns"] = extra_columns
            raw_payload = freeze_json_object(raw_payload_data)
            try:
                if extra_columns:
                    raise ValueError("row has unexpected columns")
                observations.append(self._normalize(raw_payload))
            except (KeyError, TypeError, ValueError) as error:
                failures.append(
                    SourceValidationFailure(
                        source_name=self.source_name,
                        reason=f"invalid FIRMS row: {error}",
                        raw_payload=raw_payload,
                    )
                )

        return SourceBatch(tuple(observations), tuple(failures))

    def _normalize(self, row: FrozenJsonObject) -> NormalizedObservation:
        latitude = _number(row, "latitude")
        longitude = _number(row, "longitude")
        observed_at = _observed_at(row)
        satellite = _required(row, "satellite").upper()
        instrument = _required(row, "instrument").upper()
        confidence_code = _required(row, "confidence").lower()
        try:
            confidence = _CONFIDENCE[confidence_code]
        except KeyError:
            raise ValueError("confidence is unsupported") from None

        intensity_value = row.get("bright_ti4")
        intensity = (
            _number(row, "bright_ti4")
            if intensity_value is not None
            and (not isinstance(intensity_value, str) or intensity_value.strip())
            else None
        )
        identity = "|".join(
            (
                satellite,
                instrument,
                observed_at.strftime("%Y-%m-%dT%H:%M:00Z"),
                f"{latitude:.5f}",
                f"{longitude:.5f}",
            )
        )

        return NormalizedObservation(
            source_name=self.source_name,
            source_record_id=sha256(identity.encode("utf-8")).hexdigest(),
            observed_at=observed_at,
            longitude=longitude,
            latitude=latitude,
            confidence=confidence,
            intensity=intensity,
            raw_payload=row,
        )


def _required(row: Mapping[str, object], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _number(row: Mapping[str, object], field: str) -> float:
    value = _required(row, field)
    try:
        number = float(value)
    except OverflowError:
        raise ValueError(f"{field} must be finite") from None
    except ValueError:
        raise ValueError(f"{field} must be a number") from None
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _observed_at(row: Mapping[str, object]) -> datetime:
    acquisition_date = _required(row, "acq_date")
    acquisition_time = _required(row, "acq_time")
    if (
        len(acquisition_time) != 4
        or not acquisition_time.isascii()
        or not acquisition_time.isdigit()
    ):
        raise ValueError("acquisition time is invalid")
    value = f"{acquisition_date} {acquisition_time}"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H%M").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("acquisition time is invalid") from None
