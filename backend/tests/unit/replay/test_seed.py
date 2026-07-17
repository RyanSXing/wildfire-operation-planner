from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

from wildfireops.decision.risk import RiskConfig
from wildfireops.geospatial.clustering import ClusteringConfig
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.replay.manifest import ReplayManifest, RoadGraphMetadata
from wildfireops.replay.seed import (
    ReplaySeedResult,
    _package_digest,
    _result_json,
    _seed_request_hash,
    _seed_request_payload,
)


def _manifest(files: dict[str, str] | None = None) -> ReplayManifest:
    return ReplayManifest(
        package_id="synthetic-replay-v1",
        region=(-122.4, 39.2, -120.3, 41.0),
        start_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        end_at=datetime(2024, 7, 24, 19, tzinfo=UTC),
        schema_version=1,
        algorithm_config_version="replay-v1",
        files=files
        or {
            "observations.jsonl": "a" * 64,
            "resources.json": "b" * 64,
        },
    )


def _clustering_config(radius: float = 500.0) -> ClusteringConfig:
    return ClusteringConfig(
        spatial_radius_meters=radius,
        temporal_window_seconds=300.0,
        minimum_points=3,
        algorithm_version="cluster-v1",
    )


def _manifest_with_road_graph(edge_count: int = 42) -> ReplayManifest:
    road_digest = "c" * 64
    return _manifest(
        {
            "observations.jsonl": "a" * 64,
            "resources.json": "b" * 64,
            "roads.graphml.gz": road_digest,
        }
    ).with_road_graph(
        RoadGraphMetadata(
            filename="roads.graphml.gz",
            retrieved_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
            bbox=(-122.4, 39.2, -120.3, 41.0),
            network_type="drive",
            osmnx_version="2.1.0",
            graph_digest=road_digest,
            edge_count=edge_count,
        )
    )


def test_package_digest_ignores_manifest_file_insertion_order() -> None:
    first = _manifest({"observations.jsonl": "a" * 64, "resources.json": "b" * 64})
    second = _manifest({"resources.json": "b" * 64, "observations.jsonl": "a" * 64})

    assert _package_digest(first) == _package_digest(second)


def test_package_digest_changes_for_every_semantic_manifest_change() -> None:
    manifest = _manifest()
    changed = (
        replace(
            manifest, files={"observations.jsonl": "d" * 64, "resources.json": "b" * 64}
        ),
        replace(manifest, end_at=manifest.end_at + timedelta(minutes=1)),
        replace(manifest, algorithm_config_version="replay-v2"),
    )

    assert all(_package_digest(manifest) != _package_digest(value) for value in changed)


def test_package_digest_changes_when_road_graph_metadata_changes() -> None:
    assert _package_digest(_manifest_with_road_graph()) != _package_digest(
        _manifest_with_road_graph(edge_count=43)
    )


def test_seed_request_hash_is_stable_for_equal_configs() -> None:
    package_digest = "a" * 64

    assert _seed_request_hash(
        package_digest,
        _clustering_config(),
        ExposureConfig(),
        RiskConfig(),
    ) == _seed_request_hash(
        package_digest,
        _clustering_config(),
        ExposureConfig(),
        RiskConfig(),
    )


def test_seed_request_hash_changes_for_clustering_or_exposure_config() -> None:
    package_digest = "a" * 64
    baseline = _seed_request_hash(
        package_digest,
        _clustering_config(),
        ExposureConfig(),
        RiskConfig(),
    )

    assert baseline != _seed_request_hash(
        package_digest,
        _clustering_config(radius=501.0),
        ExposureConfig(),
        RiskConfig(),
    )
    assert baseline != _seed_request_hash(
        package_digest,
        _clustering_config(),
        ExposureConfig(buffer_meters=10_001.0),
        RiskConfig(),
    )


def test_seed_request_payload_includes_every_risk_config_field() -> None:
    payload = _seed_request_payload(
        "a" * 64,
        _clustering_config(),
        ExposureConfig(),
        RiskConfig(),
    )

    assert set(payload["risk_config"]) == {field.name for field in fields(RiskConfig)}


def test_result_json_is_compact_sorted_and_snake_case() -> None:
    result = ReplaySeedResult(
        package_id="synthetic-replay-v1",
        package_digest="a" * 64,
        status="seeded",
        assets_inserted=1,
        resources_inserted=1,
        observations_inserted=3,
        incidents_created=1,
        snapshots_created=1,
    )

    assert _result_json(result) == (
        '{"assets_inserted":1,"incidents_created":1,"observations_inserted":3,'
        '"package_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"package_id":"synthetic-replay-v1","resources_inserted":1,'
        '"snapshots_created":1,"status":"seeded"}'
    )


def test_result_json_represents_an_already_seeded_result() -> None:
    result = ReplaySeedResult(
        package_id="synthetic-replay-v1",
        package_digest="a" * 64,
        status="already_seeded",
        assets_inserted=0,
        resources_inserted=0,
        observations_inserted=0,
        incidents_created=0,
        snapshots_created=0,
    )

    assert _result_json(result) == (
        '{"assets_inserted":0,"incidents_created":0,"observations_inserted":0,'
        '"package_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"package_id":"synthetic-replay-v1","resources_inserted":0,'
        '"snapshots_created":0,"status":"already_seeded"}'
    )
