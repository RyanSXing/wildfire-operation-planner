import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from shutil import copytree
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
    assert exercise_definition_digest(definition) == exercise_definition_digest(definition)


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


def _exercise_body(manifest: dict[str, Any]) -> dict[str, Any]:
    checkpoints = []
    for index, reference_at in enumerate(
        (
            "2024-07-24T18:11:00Z",
            "2024-07-24T18:12:00Z",
            "2024-07-24T18:13:00Z",
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
                "historicalWeatherSourceRecordId": "weather-1",
                "incidents": [
                    {
                        "incidentKey": "park-fire",
                        "name": "Park Fire",
                        "provenance": "historical",
                        "detectionSourceRecordIds": ["detection-1812"],
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
