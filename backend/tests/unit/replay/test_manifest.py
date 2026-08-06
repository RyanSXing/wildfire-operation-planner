import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from wildfireops.replay.manifest import (
    ReplayManifest,
    ReplayManifestInvalid,
    RoadGraphMetadata,
)


FIXTURE_MANIFEST = Path("tests/fixtures/replay-small/manifest.json")


def _manifest_payload() -> dict[str, Any]:
    return json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_manifest_rejects_unknown_schema_version(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["schema_version"] = 2

    with pytest.raises(ReplayManifestInvalid, match="unsupported schema_version: 2"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize("field", ["start_at", "end_at"])
@pytest.mark.parametrize(
    "timestamp",
    [
        "2024-07-24T18:00:00",
        "2024-07-24T20:00:00+02:00",
        "2024-07-24T18:00:00-00:00",
    ],
)
def test_manifest_requires_strict_utc_timestamps(
    tmp_path: Path,
    field: str,
    timestamp: str,
) -> None:
    payload = _manifest_payload()
    payload[field] = timestamp

    with pytest.raises(ReplayManifestInvalid, match=rf"^{field} must be UTC$"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_manifest_rejects_end_before_start(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["start_at"] = "2024-07-24T18:30:00Z"
    payload["end_at"] = "2024-07-24T18:00:00Z"

    with pytest.raises(ReplayManifestInvalid, match="end_at must not precede start_at"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize(
    "field",
    [
        "package_id",
        "region",
        "start_at",
        "end_at",
        "schema_version",
        "algorithm_config_version",
        "files",
    ],
)
def test_manifest_requires_every_schema_field(tmp_path: Path, field: str) -> None:
    payload = _manifest_payload()
    del payload[field]

    with pytest.raises(
        ReplayManifestInvalid, match=rf"missing required field: {field}"
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_manifest_rejects_unsupported_top_level_fields(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["unexpected"] = True

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^unsupported manifest field: unexpected$",
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_manifest_rejects_unsupported_region_fields(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["region"]["unexpected"] = True

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^unsupported region field: unexpected$",
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize(
    "filename",
    [
        "/tmp/observations.jsonl",
        "../observations.jsonl",
        "nested/../../observations.jsonl",
        "./observations.jsonl",
        "nested\\observations.jsonl",
        "C:/observations.jsonl",
    ],
)
def test_manifest_requires_safe_portable_relative_paths(
    tmp_path: Path,
    filename: str,
) -> None:
    payload = _manifest_payload()
    payload["files"] = {filename: "0" * 64}

    with pytest.raises(ReplayManifestInvalid, match="unsafe file path"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize("files", [{}, {"data.jsonl": "not-a-sha256"}])
def test_manifest_requires_nonempty_sha256_file_map(
    tmp_path: Path,
    files: dict[str, str],
) -> None:
    payload = _manifest_payload()
    payload["files"] = files

    with pytest.raises(ReplayManifestInvalid, match="files"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


@pytest.mark.parametrize(
    "bbox",
    [
        [-181.0, 39.2, -120.3, 41.0],
        [-122.4, -91.0, -120.3, 41.0],
        [-120.3, 39.2, -122.4, 41.0],
        [-122.4, 41.0, -120.3, 39.2],
        [-122.4, True, -120.3, 41.0],
    ],
)
def test_manifest_requires_valid_bbox(tmp_path: Path, bbox: list[object]) -> None:
    payload = _manifest_payload()
    payload["region"] = {"bbox": bbox}

    with pytest.raises(ReplayManifestInvalid, match="region.bbox"):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_manifest_rejects_an_oversized_integer_bbox_coordinate(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    payload["region"] = {"bbox": [10**400, 39.2, -120.3, 41.0]}

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^region\.bbox coordinates must be finite numbers$",
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_manifest_wraps_an_oversized_integer_token_as_invalid_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "manifest.json"
    raw_manifest = FIXTURE_MANIFEST.read_text(encoding="utf-8").replace(
        "-122.4",
        "9" * 5000,
        1,
    )
    path.write_text(raw_manifest, encoding="utf-8")

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^manifest\.json is not valid JSON$",
    ):
        ReplayManifest.load(path)


def test_legacy_manifest_remains_valid_without_road_graph_metadata() -> None:
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)

    assert manifest.road_graph is None
    assert "road_graph" not in manifest.to_payload()


def test_with_files_returns_valid_replacement_without_mutating_original() -> None:
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)

    replaced = manifest.with_files({"exercise.json": "a" * 64})

    assert "exercise.json" not in manifest.files
    assert replaced.files["exercise.json"] == "a" * 64


def test_road_graph_metadata_round_trips_atomically(tmp_path: Path) -> None:
    payload = _manifest_payload()
    digest = "a" * 64
    payload["files"]["roads.graphml.gz"] = digest
    payload["road_graph"] = {
        "filename": "roads.graphml.gz",
        "retrieved_at": "2024-07-25T12:34:56Z",
        "bbox": [-122.4, 39.2, -120.3, 41.0],
        "network_type": "drive",
        "osmnx_version": "2.1.0",
        "graph_digest": digest,
        "edge_count": 42,
    }
    manifest = ReplayManifest.load(_write_manifest(tmp_path, payload))

    assert manifest.road_graph == RoadGraphMetadata(
        filename="roads.graphml.gz",
        retrieved_at=datetime(2024, 7, 25, 12, 34, 56, tzinfo=UTC),
        bbox=(-122.4, 39.2, -120.3, 41.0),
        network_type="drive",
        osmnx_version="2.1.0",
        graph_digest=digest,
        edge_count=42,
    )
    output = tmp_path / "round-trip" / "manifest.json"
    output.parent.mkdir()
    manifest.write_atomic(output)

    assert ReplayManifest.load(output) == manifest
    assert (
        json.loads(output.read_text(encoding="utf-8"))["road_graph"]
        == payload["road_graph"]
    )


def test_atomic_write_ignores_a_preexisting_legacy_temporary(tmp_path: Path) -> None:
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)
    output = tmp_path / "manifest.json"
    unrelated = tmp_path / ".manifest.json.tmp"
    unrelated.write_bytes(b"user-owned temporary")

    manifest.write_atomic(output)

    assert ReplayManifest.load(output) == manifest
    assert unrelated.read_bytes() == b"user-owned temporary"


def test_atomic_write_failure_preserves_a_raced_unique_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)
    output = tmp_path / "manifest.json"
    output.write_bytes(b"original manifest")
    unrelated = b"replacement stage owned by another writer"

    def replace_stage_then_fail(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *args: object,
        **kwargs: object,
    ) -> None:
        source_directory = kwargs.get("src_dir_fd")
        if isinstance(source_directory, int):
            os.unlink(source, dir_fd=source_directory)
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_directory,
            )
            try:
                os.write(descriptor, unrelated)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        else:
            source_path = Path(source)
            source_path.unlink()
            source_path.write_bytes(unrelated)
        raise OSError("simulated manifest replace race")

    monkeypatch.setattr(os, "replace", replace_stage_then_fail)

    with pytest.raises(
        ReplayManifestInvalid,
        match="simulated manifest replace race",
    ):
        manifest.write_atomic(
            output,
            expected_digest=sha256(output.read_bytes()).hexdigest(),
        )

    stages = list(tmp_path.glob(".manifest.json.tmp-*"))
    assert output.read_bytes() == b"original manifest"
    assert len(stages) == 1
    assert stages[0].read_bytes() == unrelated


def test_atomic_write_requires_the_digest_of_an_existing_manifest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "manifest.json"
    original = FIXTURE_MANIFEST.read_bytes()
    output.write_bytes(original)
    updated = replace(ReplayManifest.load(output), package_id="updated")

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^expected_digest is required to replace manifest\.json$",
    ):
        updated.write_atomic(output)

    assert output.read_bytes() == original


def test_atomic_write_rejects_a_stale_manifest_digest(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    original = FIXTURE_MANIFEST.read_bytes()
    output.write_bytes(original)
    updated = replace(ReplayManifest.load(output), package_id="updated")

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^manifest\.json changed before write$",
    ):
        updated.write_atomic(output, expected_digest="0" * 64)

    assert output.read_bytes() == original


def test_atomic_write_replaces_the_exact_manifest_previously_read(
    tmp_path: Path,
) -> None:
    output = tmp_path / "manifest.json"
    original = FIXTURE_MANIFEST.read_bytes()
    output.write_bytes(original)
    updated = replace(ReplayManifest.load(output), package_id="updated")

    updated.write_atomic(output, expected_digest=sha256(original).hexdigest())

    assert ReplayManifest.load(output) == updated


def test_atomic_write_rejects_an_expected_digest_for_a_missing_manifest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "manifest.json"
    manifest = ReplayManifest.load(FIXTURE_MANIFEST)

    with pytest.raises(
        ReplayManifestInvalid,
        match=r"^cannot replace missing manifest\.json$",
    ):
        manifest.write_atomic(output, expected_digest="0" * 64)

    assert not output.exists()


def test_road_graph_metadata_digest_must_match_the_file_map(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["files"]["roads.graphml.gz"] = "b" * 64
    payload["road_graph"] = {
        "filename": "roads.graphml.gz",
        "retrieved_at": "2024-07-25T12:34:56Z",
        "bbox": [-122.4, 39.2, -120.3, 41.0],
        "network_type": "drive",
        "osmnx_version": "2.1.0",
        "graph_digest": "a" * 64,
        "edge_count": 42,
    }

    with pytest.raises(
        ReplayManifestInvalid,
        match="road_graph digest must match files",
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))


def test_road_graph_metadata_bbox_must_match_the_region(tmp_path: Path) -> None:
    payload = _manifest_payload()
    digest = "a" * 64
    payload["files"]["roads.graphml.gz"] = digest
    payload["road_graph"] = {
        "filename": "roads.graphml.gz",
        "retrieved_at": "2024-07-25T12:34:56Z",
        "bbox": [-122.3, 39.2, -120.3, 41.0],
        "network_type": "drive",
        "osmnx_version": "2.1.0",
        "graph_digest": digest,
        "edge_count": 42,
    }

    with pytest.raises(
        ReplayManifestInvalid,
        match="road_graph bbox must match manifest region",
    ):
        ReplayManifest.load(_write_manifest(tmp_path, payload))
