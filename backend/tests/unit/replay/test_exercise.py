import json
import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from shutil import copytree
import subprocess
import sys
from typing import Any

import pytest

from wildfireops.replay.exercise import (
    exercise_definition_digest,
    load_exercise_definition,
)
from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt


FIXTURE = Path("tests/fixtures/replay-small")


def test_loader_returns_only_manifest_verified_file_bytes() -> None:
    loader = ReplayLoader(FIXTURE)

    assert loader.referenced_file("fire_detections.jsonl").startswith(b"{")
    with pytest.raises(
        ReplayPackageCorrupt,
        match="file is not referenced by manifest: absent.json",
    ):
        loader.referenced_file("absent.json")


@pytest.fixture
def exercise_package(tmp_path: Path) -> Path:
    package = tmp_path / "replay"
    copytree(FIXTURE, package)
    manifest = _manifest(package)
    files = {
        "weather_observations.jsonl": _json_bytes(
            {
                "observation_type": "weather_observation",
                "source_name": "nws",
                "source_record_id": "weather-1",
                "observed_at": "2024-07-24T18:10:00Z",
                "longitude": -121.5,
                "latitude": 39.8,
                "wind_speed_mps": 5.2,
                "wind_direction_degrees": 215.0,
                "temperature_celsius": 31.5,
                "raw_payload": {"station": "test"},
            }
        )
        + b"\n",
        "static_data_versions.json": _json_bytes(
            {
                "census": "2023-acs5",
                "nasa_firms": "recorded-test-v1",
                "nws": "recorded-test-v1",
                "simulated_resources": "synthetic-v1",
            }
        ),
        "source_citations.json": _json_bytes(
            {
                "census": "https://www.census.gov/",
                "nasa_firms": "https://firms.modaps.eosdis.nasa.gov/",
                "nws": "https://www.weather.gov/",
                "simulated_resources": "WildfireOps portfolio simulation",
            }
        ),
        "exposed_assets.geojson": _json_bytes(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [-121.6, 39.8],
                        },
                        "properties": {
                            "asset_id": "community-1",
                            "asset_kind": "community",
                            "name": "Community One",
                            "population": 5000,
                            "capacity": None,
                            "source_name": "census",
                            "source_version": "2023-acs5",
                            "raw_metadata": {
                                "demand": {
                                    "required_capability": "water",
                                    "required_capacity": 2,
                                }
                            },
                        },
                    }
                ],
            }
        ),
        "resources.json": _json_bytes(
            [
                {
                    "resource_id": "engine-1",
                    "resource_type": "engine",
                    "capabilities": ["water"],
                    "capacity": 4,
                    "available": True,
                    "status": "available",
                    "geometry_geojson": {
                        "type": "Point",
                        "coordinates": [-121.61, 39.81],
                    },
                    "raw_metadata": {"simulated": True},
                }
            ]
        ),
        "road.graphml": b"test graph",
    }
    for filename, content in files.items():
        (package / filename).write_bytes(content)
        manifest["files"][filename] = sha256(content).hexdigest()
    manifest["road_graph"] = {
        "filename": "road.graphml",
        "retrieved_at": "2024-07-24T18:00:00Z",
        "bbox": manifest["region"]["bbox"],
        "network_type": "drive",
        "osmnx_version": "test",
        "graph_digest": manifest["files"]["road.graphml"],
        "edge_count": 1,
    }
    _write_manifest(package, manifest)
    rewrite_exercise(package, lambda body: body.update(_exercise_body(manifest)))
    return package


def test_loads_immutable_exercise_definition(exercise_package: Path) -> None:
    definition = load_exercise_definition(ReplayLoader(exercise_package))

    assert definition is not None
    assert definition.exercise_id == "park-fire-exercise"
    assert len(definition.checkpoints) == 3
    assert (
        exercise_definition_digest(definition)
        == "a53e243acbd3dbd3875eb4b7afa1cdac5b65492ec858c849d9656eb48ced44bd"
    )


def test_definition_nested_collections_are_immutable(
    exercise_package: Path,
) -> None:
    definition = load_exercise_definition(ReplayLoader(exercise_package))

    assert definition is not None
    with pytest.raises(TypeError):
        definition.objectives["fastest-response"] = definition.objectives[
            "fastest-response"
        ]
    with pytest.raises(TypeError):
        definition.sandbox.wind_presets["baseline"] = definition.sandbox.wind_presets[
            "baseline"
        ]
    with pytest.raises(TypeError):
        definition.sandbox.priority_multipliers["standard"] = 2


def test_definition_digest_is_stable_across_hash_seeds(
    exercise_package: Path,
) -> None:
    rewrite_exercise(
        exercise_package,
        lambda body: body["resources"][0].update(
            capabilities=["water", "medical", "road"]
        )
        or body["sandbox"].update(closureEdgeIds=["edge-a", "edge-b"]),
    )
    script = (
        "from pathlib import Path\n"
        "from wildfireops.replay.exercise import exercise_definition_digest, "
        "load_exercise_definition\n"
        "from wildfireops.replay.loader import ReplayLoader\n"
        "print(exercise_definition_digest(load_exercise_definition("
        "ReplayLoader(Path(__import__('sys').argv[1])))))\n"
    )

    digests = {
        subprocess.check_output(
            [sys.executable, "-c", script, str(exercise_package)],
            env={**os.environ, "PYTHONHASHSEED": seed},
            text=True,
        ).strip()
        for seed in ("1", "2", "3")
    }

    assert len(digests) == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda body: body.update(replayPackageId="wrong"), "replayPackageId"),
        (lambda body: body.update(graphVersion="wrong"), "graphVersion"),
        (
            lambda body: body["checkpoints"].reverse(),
            "checkpoints must be strictly time ordered",
        ),
        (
            lambda body: body["checkpoints"][0]["tasks"][0].update(
                assetId="unknown"
            ),
            "unknown asset ID: unknown",
        ),
        (
            lambda body: body["checkpoints"][0]["tasks"][0].update(
                requiredCapability="aircraft"
            ),
            "no resource supports capability: aircraft",
        ),
    ],
)
def test_definition_rejects_invalid_contract(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda body: body["assets"][0].update(name="Different Community"),
            "does not match verified static asset",
        ),
        (
            lambda body: body["assets"][0].update(
                citationUrl="https://example.invalid/"
            ),
            "does not match verified static asset",
        ),
        (
            lambda body: body["assets"][0].update(
                position={"longitude": -121.61, "latitude": 39.8}
            ),
            "does not match verified static asset",
        ),
        (
            lambda body: body["assets"][0].update(sourceRecordId="unknown"),
            "unknown verified static asset",
        ),
    ],
)
def test_definition_rejects_invalid_static_asset_reference(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda body: _external_asset(body).update(sourceName="openstreetmap"),
            "sourceName must be OpenStreetMap",
        ),
        (
            lambda body: _external_asset(body).update(sourceRecordId="node:1"),
            "sourceRecordId must be node, way, or relation",
        ),
        (
            lambda body: _external_asset(body).update(
                citationUrl="https://www.openstreetmap.org/node/999"
            ),
            "citationUrl does not match sourceRecordId",
        ),
        (
            lambda body: _external_asset(body).update(sourceVersion="not-a-timestamp"),
            "sourceVersion must be a UTC timestamp",
        ),
        (
            lambda body: _external_asset(body).update(
                sourceVersion="2026-07-23T12:45:22+00:00"
            ),
            "sourceVersion must be a UTC timestamp",
        ),
        (
            lambda body: _external_asset(body).update(name="   "),
            "name must be nonblank",
        ),
    ],
)
def test_definition_rejects_invalid_external_asset_reference(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(
        exercise_package,
        lambda body: _replace_asset_with_external(body) or mutation(body),
    )

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


def test_loads_valid_external_openstreetmap_asset(exercise_package: Path) -> None:
    rewrite_exercise(exercise_package, _replace_asset_with_external)

    assert load_exercise_definition(ReplayLoader(exercise_package)) is not None


def test_definition_rejects_duplicate_asset_source_identity(
    exercise_package: Path,
) -> None:
    rewrite_exercise(
        exercise_package,
        lambda body: body["assets"].append(
            {**body["assets"][0], "assetId": "community-duplicate"}
        ),
    )

    with pytest.raises(ReplayPackageCorrupt, match="duplicate asset source identity"):
        load_exercise_definition(ReplayLoader(exercise_package))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda body: body["checkpoints"][0].update(
                referenceAt="2024-07-24T18:12:00"
            ),
            "checkpoint referenceAt must be UTC",
        ),
        (
            lambda body: body["checkpoints"][0].update(
                referenceAt="2024-07-24T14:12:00-04:00"
            ),
            "checkpoint referenceAt must be UTC",
        ),
        (
            lambda body: body["checkpoints"][2].update(
                referenceAt="2024-07-24T18:31:00Z"
            ),
            "checkpoint referenceAt is outside replay window",
        ),
        (
            lambda body: body["checkpoints"][0].update(
                referenceAt="2024-07-24T18:11:00Z"
            ),
            "historical detection identity is after checkpoint",
        ),
        (
            lambda body: _exercise_incident(body).update(
                provenance="exercise",
                detectionIdentities=[],
                simulatedPosition={"longitude": -121.5, "latitude": 39.8},
            )
            or body["checkpoints"][0].update(referenceAt="2024-07-24T18:09:00Z"),
            "historical weather identity is after checkpoint",
        ),
    ],
)
def test_definition_rejects_invalid_checkpoint_time_or_history(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda body: _exercise_incident(body).update(
                detectionIdentities=["nws:detection-1812"]
            ),
            "unknown historical detection identity: nws:detection-1812",
        ),
        (
            lambda body: body["checkpoints"][0].update(
                historicalWeatherIdentity="nasa_firms:weather-1"
            ),
            "unknown historical weather identity: nasa_firms:weather-1",
        ),
    ],
)
def test_definition_rejects_observation_identity_with_wrong_source_prefix(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


def test_definition_accepts_replay_end_checkpoint_boundary(
    exercise_package: Path,
) -> None:
    rewrite_exercise(
        exercise_package,
        lambda body: body["checkpoints"][2].update(
            referenceAt="2024-07-24T18:30:00Z"
        ),
    )

    assert load_exercise_definition(ReplayLoader(exercise_package)) is not None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda body: _exercise_incident(body).update(
                simulatedPosition={"longitude": -121.5, "latitude": 39.8}
            ),
            "historical incident must not define simulated position",
        ),
        (
            lambda body: _exercise_incident(body).update(
                provenance="exercise",
                simulatedPosition={"longitude": -121.5, "latitude": 39.8},
            ),
            "exercise incident must not define historical detection identities",
        ),
    ],
)
def test_definition_rejects_mixed_incident_provenance(
    exercise_package: Path,
    mutation: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    rewrite_exercise(exercise_package, mutation)

    with pytest.raises(ReplayPackageCorrupt, match=message):
        load_exercise_definition(ReplayLoader(exercise_package))


def rewrite_exercise(
    package: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    manifest = _manifest(package)
    body = _exercise_body(manifest)
    mutation(body)
    content = _json_bytes(body)
    (package / "exercise.json").write_bytes(content)
    manifest["files"]["exercise.json"] = sha256(content).hexdigest()
    _write_manifest(package, manifest)


def _external_asset(body: dict[str, Any]) -> dict[str, Any]:
    return body["assets"][0]


def _exercise_incident(body: dict[str, Any]) -> dict[str, Any]:
    return body["checkpoints"][0]["incidents"][0]


def _replace_asset_with_external(body: dict[str, Any]) -> None:
    body["assets"][0] = {
        "assetId": "osm-way-546946902",
        "assetKind": "hospital",
        "name": "Enloe Medical Center",
        "position": {"longitude": -121.8504052, "latitude": 39.7423938},
        "sourceName": "OpenStreetMap",
        "sourceVersion": "2026-07-23T12:45:22Z",
        "sourceRecordId": "way/546946902",
        "citationUrl": "https://www.openstreetmap.org/way/546946902",
    }
    for checkpoint in body["checkpoints"]:
        checkpoint["tasks"][0]["assetId"] = "osm-way-546946902"


def _exercise_body(manifest: dict[str, Any]) -> dict[str, Any]:
    checkpoints = []
    for index, reference_at in enumerate(
        (
            "2024-07-24T18:12:00Z",
            "2024-07-24T18:13:00Z",
            "2024-07-24T18:14:00Z",
        ),
        start=1,
    ):
        key = f"checkpoint-{index}"
        checkpoints.append(
            {
                "checkpointKey": key,
                "title": f"Checkpoint {index}",
                "situationSummary": "A wildfire threatens the community.",
                "decisionPrompt": "Assign the available engine.",
                "referenceAt": reference_at,
                "historicalWeatherIdentity": "nws:weather-1",
                "incidents": [
                    {
                        "incidentKey": "park-fire",
                        "name": "Park Fire",
                        "provenance": "historical",
                        "detectionIdentities": ["nasa_firms:detection-1812"],
                    }
                ],
                "tasks": [
                    {
                        "taskId": f"task-{index}",
                        "incidentKey": "park-fire",
                        "assetId": "community-1",
                        "taskType": "community-evacuation",
                        "requiredCapability": "water",
                        "requiredCapacity": 1,
                        "deadlineMinutes": 15,
                        "affectedPopulation": 5000,
                        "criticalService": False,
                        "basePriority": 1,
                    }
                ],
            }
        )
    return {
        "exerciseId": "park-fire-exercise",
        "version": "v1",
        "name": "Park Fire Exercise",
        "description": "A deterministic incident response exercise.",
        "replayPackageId": manifest["package_id"],
        "graphVersion": manifest["road_graph"]["graph_digest"],
        "objectives": {
            "fastest-response": _weights(),
            "protect-critical-services": _weights(),
            "maximize-population-coverage": _weights(),
        },
        "assets": [
            {
                "assetId": "community-1",
                "assetKind": "community",
                "name": "Community One",
                "position": {"longitude": -121.6, "latitude": 39.8},
                "sourceName": "census",
                "sourceVersion": "2023-acs5",
                "sourceRecordId": "community-1",
                "citationUrl": "https://www.census.gov/",
            }
        ],
        "resources": [
            {
                "resourceId": "engine-1",
                "resourceType": "engine",
                "capabilities": ["water"],
                "capacity": 4,
                "position": {"longitude": -121.61, "latitude": 39.81},
            }
        ],
        "checkpoints": checkpoints,
        "sandbox": {
            "checkpointKeys": [item["checkpointKey"] for item in checkpoints],
            "closureEdgeIds": [],
            "windPresets": {
                "baseline": {
                    "windSpeedMps": 5.2,
                    "windDirectionDegrees": 215.0,
                }
            },
            "priorityMultipliers": {
                "standard": 1,
                "elevated": 2,
                "urgent": 3,
            },
        },
        "safetyStatement": "This exercise does not direct live operations.",
    }


def _weights() -> dict[str, int]:
    return {
        "travelWeight": 1,
        "basePriorityWeight": 1,
        "criticalServiceWeight": 1,
        "populationDivisor": 1,
        "populationWeight": 1,
    }


def _manifest(package: Path) -> dict[str, Any]:
    return json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(package: Path, payload: dict[str, Any]) -> None:
    (package / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
