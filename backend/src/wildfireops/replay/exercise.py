import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt


type ObjectivePreset = Literal[
    "fastest-response",
    "protect-critical-services",
    "maximize-population-coverage",
]
type ProvenanceKind = Literal["historical", "exercise"]


class ExerciseModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: "".join(
            word if index == 0 else word.title()
            for index, word in enumerate(value.split("_"))
        ),
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class Point(ExerciseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class ExerciseResource(ExerciseModel):
    resource_id: str = Field(min_length=1)
    resource_type: Literal["engine", "evacuation-bus", "medical-team", "road-crew"]
    capabilities: frozenset[str] = Field(min_length=1)
    capacity: int = Field(gt=0)
    available: bool = True
    position: Point
    provenance: Literal["exercise"] = "exercise"


class ExerciseAsset(ExerciseModel):
    asset_id: str = Field(min_length=1)
    asset_kind: Literal[
        "community",
        "hospital",
        "shelter",
        "communications",
        "power-substation",
        "road-corridor",
    ]
    name: str = Field(min_length=1)
    position: Point
    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    citation_url: str = Field(pattern=r"^https://")
    provenance: Literal["historical"] = "historical"


class ExerciseTask(ExerciseModel):
    task_id: str = Field(min_length=1)
    incident_key: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    task_type: Literal[
        "community-evacuation",
        "hospital-support",
        "shelter-transport",
        "communications-protection",
        "power-substation-protection",
        "corridor-clearing",
    ]
    required_capability: str = Field(min_length=1)
    required_capacity: int = Field(gt=0)
    deadline_minutes: int = Field(gt=0)
    affected_population: int = Field(ge=0)
    critical_service: bool
    base_priority: int = Field(ge=0)
    provenance: Literal["exercise"] = "exercise"


class ExerciseIncident(ExerciseModel):
    incident_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provenance: ProvenanceKind
    detection_source_record_ids: tuple[str, ...] = ()
    simulated_position: Point | None = None

    @model_validator(mode="after")
    def validate_geometry_source(self) -> "ExerciseIncident":
        if self.provenance == "historical" and not self.detection_source_record_ids:
            raise ValueError("historical incident requires detection source record IDs")
        if self.provenance == "exercise" and self.simulated_position is None:
            raise ValueError("exercise incident requires simulated position")
        return self


class ExerciseDisruption(ExerciseModel):
    wind_speed_mps: float = Field(gt=0)
    wind_direction_degrees: float = Field(ge=0, lt=360)
    closed_edge_ids: tuple[str, ...] = ()
    provenance: Literal["exercise"] = "exercise"


class ExerciseFieldReport(ExerciseModel):
    report_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    provenance: Literal["exercise"] = "exercise"


class ExerciseCheckpoint(ExerciseModel):
    checkpoint_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    situation_summary: str = Field(min_length=1)
    decision_prompt: str = Field(min_length=1)
    reference_at: datetime
    historical_weather_source_record_id: str = Field(min_length=1)
    incidents: tuple[ExerciseIncident, ...]
    tasks: tuple[ExerciseTask, ...]
    disruption: ExerciseDisruption | None = None
    field_reports: tuple[ExerciseFieldReport, ...] = ()


class ObjectiveWeights(ExerciseModel):
    travel_weight: int = Field(ge=0)
    base_priority_weight: int = Field(ge=0)
    critical_service_weight: int = Field(ge=0)
    population_divisor: int = Field(gt=0)
    population_weight: int = Field(ge=0)


class SandboxControls(ExerciseModel):
    checkpoint_keys: frozenset[str] = Field(min_length=1)
    closure_edge_ids: frozenset[str]
    wind_presets: dict[str, ExerciseDisruption]
    priority_multipliers: dict[
        Literal["standard", "elevated", "urgent"],
        int,
    ]


class ExerciseDefinition(ExerciseModel):
    exercise_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    replay_package_id: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    objectives: dict[ObjectivePreset, ObjectiveWeights]
    assets: tuple[ExerciseAsset, ...]
    resources: tuple[ExerciseResource, ...]
    checkpoints: tuple[ExerciseCheckpoint, ...] = Field(min_length=3, max_length=3)
    sandbox: SandboxControls
    safety_statement: str = Field(min_length=1)


def load_exercise_definition(
    loader: ReplayLoader,
    filename: str = "exercise.json",
) -> ExerciseDefinition | None:
    if filename not in loader.manifest.files:
        return None
    try:
        raw = json.loads(
            loader.referenced_file(filename),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        definition = ExerciseDefinition.model_validate(raw)
    except (UnicodeDecodeError, ValueError, ValidationError) as error:
        raise ReplayPackageCorrupt(
            f"{filename}: invalid exercise definition: {error}"
        ) from error
    _validate_definition_references(definition, loader)
    return definition


def exercise_definition_digest(definition: ExerciseDefinition) -> str:
    payload = json.dumps(
        definition.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return sha256(payload).hexdigest()


def _validate_definition_references(
    definition: ExerciseDefinition,
    loader: ReplayLoader,
) -> None:
    if definition.replay_package_id != loader.manifest.package_id:
        raise ReplayPackageCorrupt(
            "exercise.json: replayPackageId does not match manifest package_id"
        )
    graph = loader.manifest.road_graph
    if graph is None or definition.graph_version != graph.graph_version:
        raise ReplayPackageCorrupt(
            "exercise.json: graphVersion does not match replay graph"
        )
    if set(definition.objectives) != {
        "fastest-response",
        "protect-critical-services",
        "maximize-population-coverage",
    }:
        raise ReplayPackageCorrupt(
            "exercise.json: objectives must define all approved presets"
        )
    if loader.static_data is None:
        raise ReplayPackageCorrupt(
            "exercise.json: exercise requires replay static data"
        )
    asset_ids = [item.asset_id for item in definition.assets]
    _unique(asset_ids, "assetId")
    west, south, east, north = loader.manifest.region
    for asset in definition.assets:
        if not (
            west <= asset.position.longitude <= east
            and south <= asset.position.latitude <= north
        ):
            raise ReplayPackageCorrupt(
                f"exercise.json: asset is outside replay bounds: {asset.asset_id}"
            )
    observations = tuple(loader.iter_until(loader.manifest.end_at))
    detection_ids = {
        item.source_record_id
        for item in observations
        if isinstance(item, NormalizedObservation)
    }
    weather_ids = {
        item.source_record_id
        for item in observations
        if isinstance(item, WeatherObservation)
    }
    resource_ids = [item.resource_id for item in definition.resources]
    _unique(resource_ids, "resourceId")
    _unique(
        [item.checkpoint_key for item in definition.checkpoints],
        "checkpointKey",
    )
    checkpoint_keys = {
        item.checkpoint_key for item in definition.checkpoints
    }
    unknown_sandbox_checkpoints = sorted(
        definition.sandbox.checkpoint_keys - checkpoint_keys
    )
    if unknown_sandbox_checkpoints:
        raise ReplayPackageCorrupt(
            "exercise.json: unknown sandbox checkpoint: "
            f"{unknown_sandbox_checkpoints[0]}"
        )
    if set(definition.sandbox.priority_multipliers) != {
        "standard",
        "elevated",
        "urgent",
    }:
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox priority multipliers must define "
            "standard, elevated, and urgent"
        )
    if any(
        value <= 0
        for value in definition.sandbox.priority_multipliers.values()
    ):
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox priority multipliers must be positive"
        )
    if not definition.sandbox.wind_presets:
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox requires at least one wind preset"
        )
    if any(
        preset.closed_edge_ids
        for preset in definition.sandbox.wind_presets.values()
    ):
        raise ReplayPackageCorrupt(
            "exercise.json: sandbox wind presets cannot define road closures"
        )
    times = [item.reference_at for item in definition.checkpoints]
    if times != sorted(times) or len(set(times)) != len(times):
        raise ReplayPackageCorrupt(
            "exercise.json: checkpoints must be strictly time ordered"
        )
    for checkpoint in definition.checkpoints:
        incident_keys = [item.incident_key for item in checkpoint.incidents]
        task_ids = [item.task_id for item in checkpoint.tasks]
        report_ids = [item.report_id for item in checkpoint.field_reports]
        _unique(incident_keys, f"{checkpoint.checkpoint_key}.incidentKey")
        _unique(task_ids, f"{checkpoint.checkpoint_key}.taskId")
        _unique(report_ids, f"{checkpoint.checkpoint_key}.reportId")
        if checkpoint.historical_weather_source_record_id not in weather_ids:
            raise ReplayPackageCorrupt(
                "exercise.json: unknown weather source record ID: "
                f"{checkpoint.historical_weather_source_record_id}"
            )
        for incident in checkpoint.incidents:
            unknown = sorted(
                set(incident.detection_source_record_ids) - detection_ids
            )
            if unknown:
                raise ReplayPackageCorrupt(
                    f"exercise.json: unknown detection source record ID: {unknown[0]}"
                )
        for task in checkpoint.tasks:
            if task.incident_key not in incident_keys:
                raise ReplayPackageCorrupt(
                    f"exercise.json: task incident does not exist: {task.incident_key}"
                )
            if task.asset_id not in set(asset_ids):
                raise ReplayPackageCorrupt(
                    f"exercise.json: unknown asset ID: {task.asset_id}"
                )
            if not any(
                task.required_capability in resource.capabilities
                for resource in definition.resources
            ):
                raise ReplayPackageCorrupt(
                    "exercise.json: no resource supports capability: "
                    f"{task.required_capability}"
                )
        for report in checkpoint.field_reports:
            if report.task_id not in task_ids:
                raise ReplayPackageCorrupt(
                    f"exercise.json: field report task does not exist: "
                    f"{report.task_id}"
                )


def _unique(values: list[str], field: str) -> None:
    if len(values) != len(set(values)):
        raise ReplayPackageCorrupt(f"exercise.json: duplicate {field}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"invalid JSON number: {value}")
