import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from wildfireops.replay.build import ReplayBuildError, build_package, main
from wildfireops.replay.loader import ReplayLoader


def _jsonl(*records: dict[str, Any]) -> str:
    return "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )


def _fire_record(source_record_id: str, observed_at: str) -> dict[str, Any]:
    return {
        "observation_type": "fire_detection",
        "source_name": "nasa_firms",
        "source_record_id": source_record_id,
        "observed_at": observed_at,
        "longitude": -121.47,
        "latitude": 39.8,
        "confidence": 0.75,
        "intensity": 327.4,
        "raw_payload": {"recorded": True, "satellite": "N20"},
    }


def _weather_record(source_record_id: str, observed_at: str) -> dict[str, Any]:
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


def _staging_directory(tmp_path: Path) -> Path:
    source_dir = tmp_path / "staging"
    source_dir.mkdir()
    (source_dir / "fire_detections.jsonl").write_text(
        _jsonl(
            _fire_record("z-fire", "2024-07-24T18:18:00+00:00"),
            _fire_record("a-fire", "2024-07-24T18:12:00Z"),
        ),
        encoding="utf-8",
    )
    (source_dir / "weather_observations.jsonl").write_text(
        _jsonl(_weather_record("weather", "2024-07-24T18:10:00Z")),
        encoding="utf-8",
    )
    (source_dir / "metadata.json").write_text(
        json.dumps(
            {
                "algorithm_config_version": "test-config-v1",
                "static_data_versions": {
                    "administrative_boundaries": "recorded-test-v1"
                },
                "source_citations": {
                    "nasa_firms": "https://firms.modaps.eosdis.nasa.gov/",
                    "nws": "https://www.weather.gov/documentation/services-web-api",
                },
            }
        ),
        encoding="utf-8",
    )
    return source_dir


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _metadata(source_dir: Path) -> dict[str, Any]:
    return json.loads((source_dir / "metadata.json").read_text(encoding="utf-8"))


def _write_metadata(source_dir: Path, payload: dict[str, Any]) -> None:
    (source_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")


def _build(source_dir: Path, output: Path) -> Path:
    return build_package(
        source_dir=source_dir,
        package_id="park-fire-test-v1",
        bbox=(-122.4, 39.2, -120.3, 41.0),
        start_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        end_at=datetime(2024, 7, 24, 18, 30, tzinfo=UTC),
        output=output,
    )


def test_builder_canonicalizes_staged_replay_deterministically(
    tmp_path: Path,
) -> None:
    source_dir = _staging_directory(tmp_path)
    staged_before = _snapshot(source_dir)
    first_output = tmp_path / "first-replay"
    second_output = tmp_path / "second-replay"
    start_at = datetime(2024, 7, 24, 18, tzinfo=UTC)
    end_at = datetime(2024, 7, 24, 18, 30, tzinfo=UTC)

    assert (
        build_package(
            source_dir=source_dir,
            package_id="park-fire-test-v1",
            bbox=(-122.4, 39.2, -120.3, 41.0),
            start_at=start_at,
            end_at=end_at,
            output=first_output,
        )
        == first_output
    )
    assert (
        build_package(
            source_dir=source_dir,
            package_id="park-fire-test-v1",
            bbox=(-122.4, 39.2, -120.3, 41.0),
            start_at=start_at,
            end_at=end_at,
            output=second_output,
        )
        == second_output
    )

    assert _snapshot(source_dir) == staged_before
    assert _snapshot(first_output) == _snapshot(second_output)
    manifest = json.loads((first_output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["start_at"] == "2024-07-24T18:00:00Z"
    assert manifest["end_at"] == "2024-07-24T18:30:00Z"
    assert manifest["algorithm_config_version"] == "test-config-v1"
    assert manifest["files"].keys() == {
        "fire_detections.jsonl",
        "weather_observations.jsonl",
        "static_data_versions.json",
        "source_citations.json",
    }
    for filename, expected_hash in manifest["files"].items():
        assert (
            sha256((first_output / filename).read_bytes()).hexdigest() == expected_hash
        )
    assert json.loads(
        (first_output / "static_data_versions.json").read_text(encoding="utf-8")
    ) == {"administrative_boundaries": "recorded-test-v1"}
    assert json.loads(
        (first_output / "source_citations.json").read_text(encoding="utf-8")
    ) == {
        "nasa_firms": "https://firms.modaps.eosdis.nasa.gov/",
        "nws": "https://www.weather.gov/documentation/services-web-api",
    }
    canonical_fire_records = [
        json.loads(line)
        for line in (first_output / "fire_detections.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [record["source_record_id"] for record in canonical_fire_records] == [
        "a-fire",
        "z-fire",
    ]
    assert [record["observed_at"] for record in canonical_fire_records] == [
        "2024-07-24T18:12:00Z",
        "2024-07-24T18:18:00Z",
    ]
    assert [
        item.identity for item in ReplayLoader(first_output).iter_until(end_at)
    ] == ["nws:weather", "nasa_firms:a-fire", "nasa_firms:z-fire"]


def test_builder_wraps_an_oversized_programmatic_bbox(
    tmp_path: Path,
) -> None:
    source_dir = _staging_directory(tmp_path)

    with pytest.raises(
        ReplayBuildError,
        match=r"^region\.bbox coordinates must be finite numbers$",
    ):
        build_package(
            source_dir=source_dir,
            package_id="park-fire-test-v1",
            bbox=(10**400, 39.2, -120.3, 41.0),
            start_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            end_at=datetime(2024, 7, 24, 18, 30, tzinfo=UTC),
            output=tmp_path / "replay",
        )


def test_builder_cli_help_documents_required_offline_source_dir(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--source-dir SOURCE_DIR" in help_text
    assert "recorded normalized observations" in help_text
    assert "fire_detections.jsonl" in help_text
    assert "weather_observations.jsonl" in help_text
    assert "algorithm_config_version" in help_text
    assert "static_data_versions" in help_text
    assert "source_citations" in help_text


@pytest.mark.parametrize("field", ["static_data_versions", "source_citations"])
def test_builder_rejects_path_traversal_in_metadata_keys(
    tmp_path: Path,
    field: str,
) -> None:
    source_dir = _staging_directory(tmp_path)
    metadata = _metadata(source_dir)
    metadata[field] = {"../outside": "recorded-v1"}
    _write_metadata(source_dir, metadata)
    output = tmp_path / "replay"

    with pytest.raises(ReplayBuildError, match=rf"unsafe {field} key"):
        build_package(
            source_dir=source_dir,
            package_id="park-fire-test-v1",
            bbox=(-122.4, 39.2, -120.3, 41.0),
            start_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            end_at=datetime(2024, 7, 24, 18, 30, tzinfo=UTC),
            output=output,
        )

    assert not output.exists()


def test_builder_validation_failure_leaves_no_output_or_temporary_package(
    tmp_path: Path,
) -> None:
    source_dir = _staging_directory(tmp_path)
    (source_dir / "weather_observations.jsonl").write_text(
        _jsonl(_weather_record("weather", "2024-07-24T20:10:00+02:00")),
        encoding="utf-8",
    )
    output = tmp_path / "replay"

    with pytest.raises(ReplayBuildError, match="observed_at must be UTC"):
        _build(source_dir, output)

    assert not output.exists()
    assert list(tmp_path.glob(".replay.tmp-*")) == []


def test_builder_refuses_nonempty_output_without_changing_it(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    output = tmp_path / "replay"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    with pytest.raises(ReplayBuildError, match="output directory must be empty"):
        _build(source_dir, output)

    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not (output / "manifest.json").exists()
    assert list(tmp_path.glob(".replay.tmp-*")) == []


def test_builder_wraps_an_unusable_output_parent(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    output_parent = tmp_path / "not-a-directory"
    output_parent.write_text("blocked", encoding="utf-8")

    with pytest.raises(ReplayBuildError, match="not-a-directory"):
        _build(source_dir, output_parent / "replay")


def test_builder_atomically_replaces_an_existing_empty_output(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    output = tmp_path / "replay"
    output.mkdir()

    assert _build(source_dir, output) == output

    assert ReplayLoader(output).manifest.package_id == "park-fire-test-v1"
    assert list(tmp_path.glob(".replay.tmp-*")) == []


def test_builder_refuses_symlinked_staging_files(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    staged_weather = source_dir / "weather_observations.jsonl"
    outside = tmp_path / "outside-weather.jsonl"
    staged_weather.replace(outside)
    staged_weather.symlink_to(outside)
    output = tmp_path / "replay"

    with pytest.raises(
        ReplayBuildError,
        match="staged file must not be a symlink: weather_observations.jsonl",
    ):
        _build(source_dir, output)

    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("algorithm_config_version", " "),
        ("static_data_versions", {}),
        ("source_citations", {}),
    ],
)
def test_builder_requires_complete_nonempty_metadata(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    source_dir = _staging_directory(tmp_path)
    metadata = _metadata(source_dir)
    metadata[field] = value
    _write_metadata(source_dir, metadata)
    output = tmp_path / "replay"

    with pytest.raises(ReplayBuildError, match=field):
        _build(source_dir, output)

    assert not output.exists()


def test_builder_cli_builds_from_the_approved_offline_contract(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    output = tmp_path / "replay"

    result = main(
        [
            "--source-dir",
            str(source_dir),
            "--package-id",
            "park-fire-test-v1",
            "--bbox=-122.40,39.20,-120.30,41.00",
            "--start",
            "2024-07-24T18:00:00Z",
            "--end",
            "2024-07-24T18:30:00Z",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert ReplayLoader(output).manifest.package_id == "park-fire-test-v1"


def test_builder_preserves_unicode_line_separators_inside_raw_payload(
    tmp_path: Path,
) -> None:
    source_dir = _staging_directory(tmp_path)
    record = _fire_record("unicode", "2024-07-24T18:12:00Z")
    record["raw_payload"]["note"] = "before\u2028after"
    (source_dir / "fire_detections.jsonl").write_text(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "replay"

    _build(source_dir, output)

    fire = next(
        item
        for item in ReplayLoader(output).iter_until(
            datetime(2024, 7, 24, 18, 30, tzinfo=UTC)
        )
        if item.identity == "nasa_firms:unicode"
    )
    assert fire.raw_payload["note"] == "before\u2028after"


def test_builder_cli_rejects_the_unknown_utc_offset(tmp_path: Path) -> None:
    source_dir = _staging_directory(tmp_path)
    output = tmp_path / "replay"

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "--source-dir",
                str(source_dir),
                "--package-id",
                "park-fire-test-v1",
                "--bbox=-122.40,39.20,-120.30,41.00",
                "--start",
                "2024-07-24T18:00:00-00:00",
                "--end",
                "2024-07-24T18:30:00Z",
                "--output",
                str(output),
            ]
        )

    assert exit_info.value.code == 2
    assert not output.exists()
