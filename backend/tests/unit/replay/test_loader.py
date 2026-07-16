import json
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from shutil import copytree
from typing import Any

import pytest

import wildfireops.replay.loader as replay_loader
from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.replay.loader import (
    ReplayLoader,
    ReplayPackageCorrupt,
    ReplayRecordInvalid,
)


FIXTURE_PACKAGE = Path("tests/fixtures/replay-small")


def _copy_package(tmp_path: Path) -> Path:
    package = tmp_path / "replay"
    copytree(FIXTURE_PACKAGE, package)
    return package


def _manifest(package: Path) -> dict[str, Any]:
    return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package: Path, payload: dict[str, Any]) -> None:
    (package / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def _replace_package_files(package: Path, files: dict[str, bytes]) -> None:
    manifest = _manifest(package)
    for filename in manifest["files"]:
        path = package / filename
        if path.exists() or path.is_symlink():
            path.unlink()
    for filename, content in files.items():
        (package / filename).write_bytes(content)
    manifest["files"] = {
        filename: sha256(content).hexdigest() for filename, content in files.items()
    }
    _write_manifest(package, manifest)


def _jsonl(*records: dict[str, Any]) -> bytes:
    return b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        for record in records
    )


def _fire_record(
    source_record_id: str,
    observed_at: str = "2024-07-24T18:12:00Z",
) -> dict[str, Any]:
    return {
        "observation_type": "fire_detection",
        "source_name": "nasa_firms",
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "longitude": -121.47,
        "latitude": 39.8,
        "confidence": 0.75,
        "intensity": 327.4,
        "raw_payload": {"recorded": True, "nested": {"values": [1, 2]}},
    }


def _weather_record(
    source_record_id: str,
    observed_at: str = "2024-07-24T18:10:00Z",
) -> dict[str, Any]:
    return {
        "observation_type": "weather_observation",
        "source_name": "nws",
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "longitude": -121.5,
        "latitude": 39.85,
        "wind_speed_mps": 5.2,
        "wind_direction_degrees": 215.0,
        "temperature_celsius": 31.5,
        "raw_payload": {"recorded": True, "station": "TEST"},
    }


def test_replay_returns_identical_order_for_same_clock_time() -> None:
    package = Path("tests/fixtures/replay-small")
    cutoff = datetime(2024, 7, 24, 18, 15, tzinfo=UTC)

    first = list(ReplayLoader(package).iter_until(cutoff))
    second = list(ReplayLoader(package).iter_until(cutoff))

    assert [item.identity for item in first] == [item.identity for item in second]
    assert len(first) == 1


def test_loader_rejects_a_file_when_one_byte_changes(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    detections = package / "fire_detections.jsonl"
    content = detections.read_bytes()
    detections.write_bytes(b"X" + content[1:])

    with pytest.raises(ReplayPackageCorrupt, match="fire_detections.jsonl"):
        ReplayLoader(package)


def test_loader_checks_every_hash_before_parsing_any_observation(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    _replace_package_files(
        package,
        {
            "fire_detections.jsonl": b"not-json\n",
            "weather_observations.jsonl": _jsonl(_weather_record("weather")),
        },
    )
    weather = package / "weather_observations.jsonl"
    content = weather.read_bytes()
    weather.write_bytes(b"X" + content[1:])

    with pytest.raises(
        ReplayPackageCorrupt,
        match="hash mismatch for weather_observations.jsonl",
    ):
        ReplayLoader(package)


def test_loader_parses_the_same_bytes_that_it_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _copy_package(tmp_path)
    _replace_package_files(
        package,
        {"fire_detections.jsonl": _jsonl(_fire_record("captured"))},
    )
    replacement = _jsonl(_fire_record("replacement"))
    original_hash = replay_loader._sha256_file

    def hash_then_replace(path: Path) -> object:
        result = original_hash(path)
        if path.name == "fire_detections.jsonl":
            path.write_bytes(replacement)
        return result

    monkeypatch.setattr(replay_loader, "_sha256_file", hash_then_replace)

    observations = list(
        ReplayLoader(package).iter_until(datetime(2024, 7, 24, 18, 30, tzinfo=UTC))
    )

    assert [item.identity for item in observations] == ["nasa_firms:captured"]


def test_loader_rejects_a_missing_referenced_file(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    (package / "fire_detections.jsonl").unlink()

    with pytest.raises(
        ReplayPackageCorrupt,
        match="missing referenced file: fire_detections.jsonl",
    ):
        ReplayLoader(package)


def test_loader_wraps_a_missing_manifest_as_package_corruption(tmp_path: Path) -> None:
    package = tmp_path / "replay"
    package.mkdir()

    with pytest.raises(ReplayPackageCorrupt, match="manifest.json"):
        ReplayLoader(package)


def test_loader_wraps_an_oversized_manifest_bbox_as_package_corruption(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    manifest = _manifest(package)
    manifest["region"] = {"bbox": [10**400, 39.2, -120.3, 41.0]}
    _write_manifest(package, manifest)

    with pytest.raises(
        ReplayPackageCorrupt,
        match=r"region\.bbox coordinates must be finite numbers",
    ):
        ReplayLoader(package)


def test_loader_rejects_an_empty_referenced_file(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    detections = package / "fire_detections.jsonl"
    detections.write_bytes(b"")
    manifest = _manifest(package)
    manifest["files"]["fire_detections.jsonl"] = sha256(b"").hexdigest()
    _write_manifest(package, manifest)

    with pytest.raises(
        ReplayPackageCorrupt,
        match="empty referenced file: fire_detections.jsonl",
    ):
        ReplayLoader(package)


def test_loader_does_not_follow_referenced_symlinks(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    detections = package / "fire_detections.jsonl"
    outside = tmp_path / "outside.jsonl"
    detections.replace(outside)
    detections.symlink_to(outside)

    with pytest.raises(
        ReplayPackageCorrupt,
        match="referenced file must not be a symlink: fire_detections.jsonl",
    ):
        ReplayLoader(package)


def test_loader_requires_nonempty_observation_data(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    metadata = package / "metadata.json"
    metadata.write_text('{"version":"test-v1"}\n', encoding="utf-8")
    manifest = _manifest(package)
    manifest["files"] = {
        "metadata.json": sha256(metadata.read_bytes()).hexdigest(),
    }
    _write_manifest(package, manifest)

    with pytest.raises(ReplayPackageCorrupt, match="no observation JSONL files"):
        ReplayLoader(package)


def test_loader_returns_fresh_fire_and_weather_values_in_stable_order(
    tmp_path: Path,
) -> None:
    package = _copy_package(tmp_path)
    _replace_package_files(
        package,
        {
            "fire_detections.jsonl": _jsonl(
                _fire_record("z-fire"),
                _fire_record("a-fire"),
            ),
            "weather_observations.jsonl": _jsonl(_weather_record("weather")),
        },
    )
    loader = ReplayLoader(package)
    cutoff = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)

    first = list(loader.iter_until(cutoff))
    second = list(loader.iter_until(cutoff))

    assert [item.identity for item in first] == [
        "nws:weather",
        "nasa_firms:a-fire",
        "nasa_firms:z-fire",
    ]
    assert isinstance(first[0], WeatherObservation)
    assert isinstance(first[1], NormalizedObservation)
    assert first == second
    assert all(left is not right for left, right in zip(first, second, strict=True))
    assert all(
        left.raw_payload is not right.raw_payload
        for left, right in zip(first, second, strict=True)
    )


def test_loader_reports_filename_and_line_for_malformed_json(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    content = _jsonl(_fire_record("valid")) + b'{"broken"\n'
    _replace_package_files(package, {"fire_detections.jsonl": content})

    with pytest.raises(
        ReplayRecordInvalid,
        match=r"^fire_detections\.jsonl:2: invalid JSON$",
    ):
        ReplayLoader(package)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("unsupported_type", "unsupported observation_type: smoke_observation"),
        ("missing_field", "missing required field: confidence"),
        ("naive_timestamp", "observed_at must be UTC"),
        ("nonzero_offset", "observed_at must be UTC"),
        ("unknown_offset", "observed_at must be UTC"),
        ("boolean_number", "confidence must be a finite number"),
        ("non_object_payload", "raw_payload must be an object"),
    ],
)
def test_loader_rejects_invalid_records_with_stable_context(
    tmp_path: Path,
    case: str,
    reason: str,
) -> None:
    package = _copy_package(tmp_path)
    record = _fire_record("invalid")
    if case == "unsupported_type":
        record["observation_type"] = "smoke_observation"
    elif case == "missing_field":
        del record["confidence"]
    elif case == "naive_timestamp":
        record["observed_at"] = "2024-07-24T18:12:00"
    elif case == "nonzero_offset":
        record["observed_at"] = "2024-07-24T20:12:00+02:00"
    elif case == "unknown_offset":
        record["observed_at"] = "2024-07-24T18:12:00-00:00"
    elif case == "boolean_number":
        record["confidence"] = True
    elif case == "non_object_payload":
        record["raw_payload"] = []
    _replace_package_files(package, {"fire_detections.jsonl": _jsonl(record)})

    with pytest.raises(
        ReplayRecordInvalid,
        match=rf"^fire_detections\.jsonl:1: {reason}$",
    ):
        ReplayLoader(package)


def test_loader_rejects_unsupported_observation_files(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    _replace_package_files(
        package,
        {"smoke_observations.jsonl": _jsonl(_fire_record("fire"))},
    )

    with pytest.raises(
        ReplayPackageCorrupt,
        match="unsupported observation file: smoke_observations.jsonl",
    ):
        ReplayLoader(package)


def test_loader_rejects_duplicate_source_identities(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    _replace_package_files(
        package,
        {
            "fire_detections.jsonl": _jsonl(
                _fire_record("duplicate"),
                _fire_record("duplicate", "2024-07-24T18:18:00Z"),
            )
        },
    )

    with pytest.raises(
        ReplayRecordInvalid,
        match=(
            r"^fire_detections\.jsonl:2: duplicate source identity: "
            r"nasa_firms:duplicate$"
        ),
    ):
        ReplayLoader(package)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("observed_at", "2024-07-24T17:59:00Z", "outside manifest time range"),
        ("longitude", -123.0, "outside manifest region.bbox"),
        ("latitude", 42.0, "outside manifest region.bbox"),
    ],
)
def test_loader_rejects_observations_outside_manifest_scope(
    tmp_path: Path,
    field: str,
    value: object,
    reason: str,
) -> None:
    package = _copy_package(tmp_path)
    record = _fire_record("outside")
    record[field] = value
    _replace_package_files(package, {"fire_detections.jsonl": _jsonl(record)})

    with pytest.raises(
        ReplayRecordInvalid,
        match=rf"^fire_detections\.jsonl:1: observation is {reason}$",
    ):
        ReplayLoader(package)


@pytest.mark.parametrize(
    "cutoff",
    [
        datetime(2024, 7, 24, 18, 15),
        datetime(
            2024,
            7,
            24,
            20,
            15,
            tzinfo=timezone(timedelta(hours=2)),
        ),
    ],
)
def test_iter_until_requires_a_strict_utc_cutoff(cutoff: datetime) -> None:
    loader = ReplayLoader(FIXTURE_PACKAGE)

    with pytest.raises(ValueError, match="^at must be UTC$"):
        list(loader.iter_until(cutoff))
