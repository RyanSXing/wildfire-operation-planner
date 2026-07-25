import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from hashlib import sha256
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.replay.loader import ReplayLoader, ReplayPackageCorrupt


type ObjectivePreset = Literal[
    "fastest-response",
    "protect-critical-services",
    "maximize-population-coverage",
]
type ProvenanceKind = Literal["historical", "exercise"]
type StrictPositiveInt = Annotated[StrictInt, Field(gt=0, le=2**63 - 1)]
type StrictNonNegativeInt = Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]


_OSM_RECORD_ID = re.compile(r"(?:node|way|relation)/[1-9][0-9]*$")
_OSM_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)


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

    def model_post_init(self, __context: object) -> None:
        for field in type(self).model_fields:
            object.__setattr__(self, field, _freeze(getattr(self, field)))


class Point(ExerciseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)


class ExerciseResource(ExerciseModel):
    resource_id: str = Field(min_length=1)
    resource_type: Literal["engine", "evacuation-bus", "medical-team", "road-crew"]
    capabilities: frozenset[str] = Field(min_length=1)
    capacity: StrictPositiveInt
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
    required_capacity: StrictPositiveInt
    deadline_minutes: StrictPositiveInt
    affected_population: StrictNonNegativeInt
    critical_service: bool
    base_priority: StrictNonNegativeInt
    provenance: Literal["exercise"] = "exercise"


class ExerciseIncident(ExerciseModel):
    incident_key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provenance: ProvenanceKind
    detection_identities: tuple[str, ...] = ()
    simulated_position: Point | None = None

    @model_validator(mode="after")
    def validate_geometry_source(self) -> "ExerciseIncident":
        if self.provenance == "historical":
            if not self.detection_identities:
                raise ValueError("historical incident requires detection identities")
            if self.simulated_position is not None:
                raise ValueError("historical incident must not define simulated position")
        else:
            if self.detection_identities:
                raise ValueError(
                    "exercise incident must not define historical detection identities"
                )
            if self.simulated_position is None:
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
    historical_weather_identity: str = Field(min_length=1)
    incidents: tuple[ExerciseIncident, ...]
    tasks: tuple[ExerciseTask, ...]
    disruption: ExerciseDisruption | None = None
    field_reports: tuple[ExerciseFieldReport, ...] = ()


class ObjectiveWeights(ExerciseModel):
    travel_weight: StrictNonNegativeInt
    base_priority_weight: StrictNonNegativeInt
    critical_service_weight: StrictNonNegativeInt
    population_divisor: StrictPositiveInt
    population_weight: StrictNonNegativeInt


class SandboxControls(ExerciseModel):
    checkpoint_keys: frozenset[str] = Field(min_length=1)
    closure_edge_ids: tuple[str, ...]
    wind_presets: Mapping[str, ExerciseDisruption]
    priority_multipliers: Mapping[
        Literal["standard", "elevated", "urgent"],
        Annotated[StrictInt, Field(gt=0, le=2**63 - 1)],
    ]

    @field_validator("closure_edge_ids", mode="before")
    @classmethod
    def validate_unique_closure_edges(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        first_index_by_edge: dict[str, int] = {}
        for index, edge_id in enumerate(value):
            if not isinstance(edge_id, str):
                continue
            first_index = first_index_by_edge.setdefault(edge_id, index)
            if first_index != index:
                raise ValueError(
                    "sandbox.closureEdgeIds: duplicate closure edge "
                    f"{edge_id!r} at indices {first_index} and {index}"
                )
        return tuple(value)


class ExerciseDefinition(ExerciseModel):
    exercise_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    replay_package_id: str = Field(min_length=1)
    graph_version: str = Field(min_length=1)
    objectives: Mapping[ObjectivePreset, ObjectiveWeights]
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
        _canonicalize(definition),
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
    _unique(
        [f"{item.source_name}:{item.source_record_id}" for item in definition.assets],
        "asset source identity",
    )
    west, south, east, north = loader.manifest.region
    for asset in definition.assets:
        if not (
            west <= asset.position.longitude <= east
            and south <= asset.position.latitude <= north
        ):
            raise ReplayPackageCorrupt(
                f"exercise.json: asset is outside replay bounds: {asset.asset_id}"
            )
        _validate_asset_reference(asset, loader)
    observations = tuple(loader.iter_until(loader.manifest.end_at))
    detection_observed_at = {
        item.identity: item.observed_at
        for item in observations
        if isinstance(item, NormalizedObservation)
    }
    weather_observed_at = {
        item.identity: item.observed_at
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
    maximum_multiplier = max(definition.sandbox.priority_multipliers.values())
    for checkpoint_index, checkpoint in enumerate(definition.checkpoints):
        for objective, weights in definition.objectives.items():
            total_penalty = 0
            for task_index, task in enumerate(checkpoint.tasks):
                penalty = 0
                for field, term in (
                    ("basePriority", weights.base_priority_weight * task.base_priority),
                    (
                        "criticalService",
                        weights.critical_service_weight * int(task.critical_service),
                    ),
                    (
                        "affectedPopulation",
                        weights.population_weight
                        * (task.affected_population // weights.population_divisor),
                    ),
                ):
                    penalty += term
                    if penalty > (2**63 - 1) // maximum_multiplier:
                        raise ReplayPackageCorrupt(
                            "exercise.json: "
                            f"objectives.{objective}, checkpoints[{checkpoint_index}]"
                            f".tasks[{task_index}].{field}: "
                            "CP-SAT integer range exceeded"
                        )
                scaled_penalty = penalty * maximum_multiplier
                if total_penalty > (2**63 - 1) - scaled_penalty:
                    raise ReplayPackageCorrupt(
                        "exercise.json: "
                        f"objectives.{objective}, checkpoints[{checkpoint_index}]"
                        f".tasks[{task_index}]: CP-SAT integer range exceeded"
                    )
                total_penalty += scaled_penalty
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
    for value in times:
        if value.utcoffset() != timedelta(0):
            raise ReplayPackageCorrupt("exercise.json: checkpoint referenceAt must be UTC")
        if value < loader.manifest.start_at or value > loader.manifest.end_at:
            raise ReplayPackageCorrupt(
                "exercise.json: checkpoint referenceAt is outside replay window"
            )
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
        weather_at = weather_observed_at.get(checkpoint.historical_weather_identity)
        if weather_at is None:
            raise ReplayPackageCorrupt(
                "exercise.json: unknown historical weather identity: "
                f"{checkpoint.historical_weather_identity}"
            )
        if weather_at > checkpoint.reference_at:
            raise ReplayPackageCorrupt(
                "exercise.json: historical weather identity is after checkpoint: "
                f"{checkpoint.historical_weather_identity}"
            )
        for incident in checkpoint.incidents:
            unknown = sorted(
                set(incident.detection_identities) - detection_observed_at.keys()
            )
            if unknown:
                raise ReplayPackageCorrupt(
                    f"exercise.json: unknown historical detection identity: {unknown[0]}"
                )
            future = sorted(
                identity
                for identity in incident.detection_identities
                if detection_observed_at[identity] > checkpoint.reference_at
            )
            if future:
                raise ReplayPackageCorrupt(
                    "exercise.json: historical detection identity is after checkpoint: "
                    f"{future[0]}"
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


def _validate_asset_reference(
    asset: ExerciseAsset,
    loader: ReplayLoader,
) -> None:
    if asset.source_name == "OpenStreetMap" or _OSM_RECORD_ID.fullmatch(
        asset.source_record_id
    ):
        if asset.source_name != "OpenStreetMap":
            raise ReplayPackageCorrupt(
                "exercise.json: external asset sourceName must be OpenStreetMap: "
                f"{asset.asset_id}"
            )
        _validate_openstreetmap_asset(asset)
        return
    assert loader.static_data is not None
    static_asset = next(
        (
            item
            for item in loader.static_data.assets
            if item.asset_id == asset.source_record_id
        ),
        None,
    )
    if static_asset is None or static_asset.asset_kind != "community":
        raise ReplayPackageCorrupt(
            f"exercise.json: unknown verified static asset: {asset.asset_id}"
        )
    coordinates = static_asset.geometry_geojson["coordinates"]
    if not isinstance(coordinates, tuple) or len(coordinates) != 2:
        raise ReplayPackageCorrupt(
            f"exercise.json: invalid verified static asset geometry: {asset.asset_id}"
        )
    expected_citation = loader.static_data.source_citations.get(
        static_asset.source_name
    )
    if (
        asset.asset_id != static_asset.asset_id
        or asset.asset_kind != static_asset.asset_kind
        or asset.name != static_asset.name
        or asset.position.longitude != coordinates[0]
        or asset.position.latitude != coordinates[1]
        or asset.source_name != static_asset.source_name
        or asset.source_version != static_asset.source_version
        or asset.citation_url != expected_citation
    ):
        raise ReplayPackageCorrupt(
            f"exercise.json: asset does not match verified static asset: {asset.asset_id}"
        )


def _validate_openstreetmap_asset(asset: ExerciseAsset) -> None:
    if not _OSM_RECORD_ID.fullmatch(asset.source_record_id):
        raise ReplayPackageCorrupt(
            "exercise.json: external asset sourceRecordId must be node, way, or "
            f"relation: {asset.asset_id}"
        )
    expected_citation = f"https://www.openstreetmap.org/{asset.source_record_id}"
    if asset.citation_url != expected_citation:
        raise ReplayPackageCorrupt(
            "exercise.json: external asset citationUrl does not match sourceRecordId: "
            f"{asset.asset_id}"
        )
    if _OSM_TIMESTAMP.fullmatch(asset.source_version) is None:
        raise ReplayPackageCorrupt(
            "exercise.json: external asset sourceVersion must be a UTC timestamp: "
            f"{asset.asset_id}"
        ) from None
    try:
        datetime.strptime(asset.source_version, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ReplayPackageCorrupt(
            "exercise.json: external asset sourceVersion must be a UTC timestamp: "
            f"{asset.asset_id}"
        ) from None
    if not asset.name.strip():
        raise ReplayPackageCorrupt(
            f"exercise.json: external asset name must be nonblank: {asset.asset_id}"
        )


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _canonicalize(value: object) -> object:
    if isinstance(value, BaseModel):
        return {
            field.alias or name: _canonicalize(item)
            for name, field in type(value).model_fields.items()
            if (item := getattr(value, name)) is not None
        }
    if isinstance(value, Mapping):
        return {
            key: _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda item: item[0])
        }
    if isinstance(value, tuple) or isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, frozenset) or isinstance(value, set):
        values = [_canonicalize(item) for item in value]
        return sorted(
            values,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


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
