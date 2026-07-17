# Offline Replay Package Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing offline replay package so a validated build can carry canonical exposed assets and explicitly simulated resources alongside fire and weather observations.

**Architecture:** Keep `ReplayManifest` schema version 1 and the existing package directory. Add one focused static-data module shared by the builder and loader; the builder always emits the complete four-file static group, while the loader preserves compatibility with legacy packages that have observations and the two provenance maps but no entity files. Presence of either entity file opts into the complete contract and requires all four files. This slice stops at package parsing and canonicalization: database seeding, replay-mode API startup, real Park Fire acquisition, golden outputs, Playwright, and benchmarks remain separate review units.

**Tech Stack:** Python 3.12, dataclasses, strict standard-library JSON parsing, Shapely, existing replay manifest/builder/loader, pytest, Ruff, mypy.

## Global Constraints

- Do not access the network or require `WILDFIREOPS_FIRMS_MAP_KEY` in this slice.
- Do not label synthetic fixtures as Park Fire data and do not create `data/replay/park-fire` yet.
- Do not add a replay HTTP endpoint, database writes, a second manifest type, a validation framework, or a new dependency.
- Preserve manifest schema version `1`; a legacy package with no asset/resource entity file has `static_data is None`. If either `exposed_assets.geojson` or `resources.json` is referenced, all four static-group files are required.
- The complete static group is exactly `static_data_versions.json`, `source_citations.json`, `exposed_assets.geojson`, and `resources.json`.
- `exposed_assets.geojson` is a GeoJSON `FeatureCollection`; each feature stores `asset_id` in properties, not a duplicate top-level feature `id`.
- `resources.json` is a top-level JSON array matching the persisted resource-state field names.
- Every asset must have exact source/version provenance and usable `raw_metadata.demand`; every resource must be explicitly simulated.
- In every complete package, each fire/weather observation `source_name` must appear in both `static_data_versions.json` and `source_citations.json`.
- Reject duplicate JSON keys, `NaN`/infinity, unsupported fields, unsafe strings, duplicate IDs/capabilities, empty or invalid geometry, and geometry outside the manifest bbox.
- Every GeoJSON position is exactly two finite numeric coordinates; booleans and three-dimensional positions are invalid.
- Canonical output uses UTF-8, one trailing newline, sorted object keys, compact separators, stable entity ordering, and sorted resource capabilities.
- Keep safety, accessibility, transaction behavior, and all existing replay/road-graph tests unchanged.

---

## File structure

- Create `backend/src/wildfireops/replay/static_data.py`: immutable static package values, strict parsing, provenance and geometry validation, and canonical payload projection.
- Modify `backend/src/wildfireops/replay/loader.py`: parse an all-or-none static group after every referenced file is hash-verified and expose `ReplayLoader.static_data`.
- Modify `backend/src/wildfireops/replay/build.py`: require staged assets/resources, validate them through the shared contract, emit canonical files, hash them, and document the complete staging input.
- Create `backend/tests/unit/replay/test_static_data.py`: focused contract tests independent of filesystem publication.
- Modify `backend/tests/unit/replay/test_loader.py`: complete/partial/legacy package integration at the loader boundary.
- Modify `backend/tests/unit/replay/test_builder.py`: complete staging, deterministic output, manifest membership, and builder error translation.

---

### Task 1: Define the immutable static-data contract

**Files:**
- Create: `backend/src/wildfireops/replay/static_data.py`
- Create: `backend/tests/unit/replay/test_static_data.py`

**Interfaces:**
- Consumes: `ReplayManifest.region`; `FrozenJsonObject`, `freeze_json_object` from `wildfireops.domain.observations`; Shapely `shape` validation.
- Produces: `STATIC_DATA_FILENAMES`, `ReplayAsset`, `ReplayResource`, `ReplayStaticData`, `ReplayStaticDataInvalid`, `parse_replay_static_data(files, manifest)`, and `static_data_payloads(data)`.

- [ ] **Step 1: Write successful parsing and canonical projection tests**

Use this minimal complete contract in `test_static_data.py`:

```python
import json
from datetime import UTC, datetime

from wildfireops.replay.manifest import ReplayManifest
from wildfireops.replay.static_data import (
    parse_replay_static_data,
    static_data_payloads,
)


def _manifest() -> ReplayManifest:
    return ReplayManifest(
        package_id="synthetic-replay-v1",
        region=(-122.4, 39.2, -120.3, 41.0),
        start_at=datetime(2024, 7, 24, tzinfo=UTC),
        end_at=datetime(2024, 7, 25, tzinfo=UTC),
        schema_version=1,
        algorithm_config_version="test-config-v1",
        files={"fire_detections.jsonl": "0" * 64},
    )


def _complete_files() -> dict[str, bytes]:
    return {
        "static_data_versions.json": json.dumps(
            {"census": "2023-acs5", "simulated_resources": "synthetic-v1"}
        ).encode(),
        "source_citations.json": json.dumps(
            {"census": "https://www.census.gov/", "simulated_resources": "WildfireOps portfolio simulation"}
        ).encode(),
        "exposed_assets.geojson": json.dumps({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-121.6, 39.8]},
                    "properties": {
                        "asset_id": "community-1",
                        "asset_kind": "community",
                        "name": "Community One",
                        "population": 5000,
                        "capacity": None,
                        "source_name": "census",
                        "source_version": "2023-acs5",
                        "raw_metadata": {
                            "demand": {"required_capability": "water", "required_capacity": 2}
                        },
                    },
                }
            ],
        }).encode(),
        "resources.json": json.dumps([
            {
                "resource_id": "engine-1",
                "resource_type": "engine",
                "capabilities": ["water", "medical"],
                "capacity": 4,
                "available": True,
                "status": "available",
                "geometry_geojson": {"type": "Point", "coordinates": [-121.61, 39.81]},
                "raw_metadata": {"simulated": True},
            }
        ]).encode(),
    }


def test_static_data_is_sorted_immutable_and_projects_canonically() -> None:
    data = parse_replay_static_data(_complete_files(), _manifest())
    payloads = static_data_payloads(data)

    assert [item.asset_id for item in data.assets] == ["community-1"]
    assert data.resources[0].capabilities == ("medical", "water")
    assert payloads["exposed_assets.geojson"]["type"] == "FeatureCollection"
    assert payloads["resources.json"][0]["raw_metadata"] == {"simulated": True}
```

Add a second valid asset before `community-1` and a second resource before `engine-1` in input, then assert output ordering is by natural ID rather than input order. Attempt assignment to a frozen dataclass field and mutation of frozen metadata to prove the returned contract is immutable.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_static_data.py -q
```

Expected: collection/import fails because `wildfireops.replay.static_data` does not exist.

- [ ] **Step 3: Write invalid-contract tests**

Parameterize one mutation per invariant and assert a stable `ReplayStaticDataInvalid` message containing the filename plus entity context:

```python
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("duplicate_asset", r"exposed_assets\.geojson: duplicate asset_id: community-1"),
        ("missing_demand", r"community-1: raw_metadata\.demand is required"),
        ("unknown_asset_field", r"community-1: unsupported property: extra"),
        ("asset_source_version_mismatch", r"community-1: source_version does not match static_data_versions"),
        ("asset_outside_bbox", r"community-1: geometry is outside manifest region\.bbox"),
        ("boolean_asset_coordinate", r"community-1: geometry coordinates must be finite two-dimensional numbers"),
        ("three_dimensional_asset", r"community-1: geometry coordinates must be finite two-dimensional numbers"),
        ("resource_not_point", r"engine-1: geometry_geojson must be a Point"),
        ("resource_outside_bbox", r"engine-1: geometry is outside manifest region\.bbox"),
        ("resource_not_simulated", r"engine-1: raw_metadata\.simulated must be true"),
        ("duplicate_capability", r"engine-1: capabilities contain duplicates"),
        ("partial_static_group", r"missing required static file: resources\.json"),
    ],
)
def test_static_data_rejects_invalid_contract(case: str, message: str) -> None:
    files = _mutated_complete_files(case)
    with pytest.raises(ReplayStaticDataInvalid, match=message):
        parse_replay_static_data(files, _manifest())
```

Also cover duplicate JSON keys, non-finite numbers, non-object `FeatureCollection`, empty features/resources, nonblank identifiers, nonnegative optional asset population/capacity, positive integer demand/resource capacity, missing source citation, invalid/empty Shapely geometry, and duplicate resource IDs.

- [ ] **Step 4: Implement the minimal static-data module**

Define the public values and function signatures exactly:

```python
STATIC_DATA_FILENAMES = (
    "static_data_versions.json",
    "source_citations.json",
    "exposed_assets.geojson",
    "resources.json",
)


class ReplayStaticDataInvalid(ValueError):
    """Raised when replay static context is missing or malformed."""


@dataclass(frozen=True, slots=True)
class ReplayAsset:
    asset_id: str
    asset_kind: str
    name: str
    population: int | None
    capacity: int | None
    source_name: str
    source_version: str
    geometry_geojson: FrozenJsonObject
    raw_metadata: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class ReplayResource:
    resource_id: str
    resource_type: str
    capabilities: tuple[str, ...]
    capacity: int
    available: bool
    status: str
    geometry_geojson: FrozenJsonObject
    raw_metadata: FrozenJsonObject


@dataclass(frozen=True, slots=True)
class ReplayStaticData:
    static_data_versions: Mapping[str, str]
    source_citations: Mapping[str, str]
    assets: tuple[ReplayAsset, ...]
    resources: tuple[ReplayResource, ...]


def parse_replay_static_data(
    files: Mapping[str, bytes],
    manifest: ReplayManifest,
) -> ReplayStaticData:
    missing = [name for name in STATIC_DATA_FILENAMES if name not in files]
    if missing:
        raise ReplayStaticDataInvalid(f"missing required static file: {missing[0]}")
    versions = _string_map(
        _strict_json(files["static_data_versions.json"], "static_data_versions.json"),
        "static_data_versions.json",
    )
    citations = _string_map(
        _strict_json(files["source_citations.json"], "source_citations.json"),
        "source_citations.json",
    )
    assets = _assets(
        _strict_json(files["exposed_assets.geojson"], "exposed_assets.geojson"),
        versions,
        citations,
        manifest.region,
    )
    resources = _resources(
        _strict_json(files["resources.json"], "resources.json"),
        manifest.region,
    )
    if "simulated_resources" not in versions:
        raise ReplayStaticDataInvalid(
            "static_data_versions.json missing required key: simulated_resources"
        )
    if "simulated_resources" not in citations:
        raise ReplayStaticDataInvalid(
            "source_citations.json missing required key: simulated_resources"
        )
    return ReplayStaticData(
        static_data_versions=MappingProxyType(dict(sorted(versions.items()))),
        source_citations=MappingProxyType(dict(sorted(citations.items()))),
        assets=tuple(sorted(assets, key=lambda item: item.asset_id)),
        resources=tuple(sorted(resources, key=lambda item: item.resource_id)),
    )


def static_data_payloads(data: ReplayStaticData) -> dict[str, object]:
    return {
        "static_data_versions.json": dict(data.static_data_versions),
        "source_citations.json": dict(data.source_citations),
        "exposed_assets.geojson": {
            "type": "FeatureCollection",
            "features": [_asset_feature(item) for item in data.assets],
        },
        "resources.json": [_resource_record(item) for item in data.resources],
    }
```

The private parsers and projectors used above must perform these concrete operations:

1. Require the four exact filenames and reject partial groups.
2. Decode strict UTF-8 JSON with `object_pairs_hook` duplicate-key rejection and `parse_constant` rejection.
3. Require nonempty string maps for versions/citations and freeze copies with `MappingProxyType`.
4. Require asset `FeatureCollection`/`Feature` objects with exact fields. Parse `properties`, validate demand metadata, and call Shapely `shape` on geometry.
5. Before calling Shapely, recursively inspect every GeoJSON position and require exactly two `int | float` values excluding `bool`, both finite. Accept asset geometry types `Point`, `Polygon`, and `MultiPolygon`; require nonempty valid geometry whose bounds lie within the manifest bbox.
6. Require asset `source_version == static_data_versions[source_name]` and a citation for `source_name`.
7. Require a nonempty top-level resource list. Validate exact fields, a two-dimensional finite `Point` inside the manifest bbox, unique sorted nonblank capabilities, positive integer capacity, boolean availability, and `raw_metadata.simulated is True`.
8. Require `simulated_resources` entries in both provenance maps.
9. Sort assets/resources by ID and materialize fresh canonical dictionaries from frozen data in `static_data_payloads`.

Do not create a generic schema framework. Small private helpers such as `_strict_json`, `_object`, `_exact_fields`, `_nonblank`, `_optional_nonnegative_integer`, `_positive_integer`, `_geometry`, and `_materialize_json` are sufficient.

- [ ] **Step 5: Run focused tests and quality checks**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_static_data.py -q
uv run ruff format --check src/wildfireops/replay/static_data.py tests/unit/replay/test_static_data.py
uv run ruff check src/wildfireops/replay/static_data.py tests/unit/replay/test_static_data.py
uv run mypy src
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit the contract**

```bash
git add backend/src/wildfireops/replay/static_data.py backend/tests/unit/replay/test_static_data.py
git commit -m "feat: define replay static data contract"
```

---

### Task 2: Load complete static context after package hash verification

**Files:**
- Modify: `backend/src/wildfireops/replay/loader.py`
- Modify: `backend/tests/unit/replay/test_loader.py`

**Interfaces:**
- Consumes: `STATIC_DATA_FILENAMES`, `ReplayStaticData`, `ReplayStaticDataInvalid`, and `parse_replay_static_data` from Task 1.
- Produces: `ReplayLoader.static_data: ReplayStaticData | None`.

- [ ] **Step 1: Write loader boundary tests**

Add a helper that copies `replay-small`, writes the four static files from Task 1, adds their SHA-256 values to `manifest.files`, and rewrites the manifest. Test:

The helper's provenance maps must also contain
`"nasa_firms": "recorded-test-v1"` and a NASA FIRMS citation because the
fixture's observation records use `source_name="nasa_firms"`.

```python
def test_loader_exposes_hash_verified_static_context(tmp_path: Path) -> None:
    package = _copy_package(tmp_path)
    _add_static_group(package)

    loader = ReplayLoader(package)

    assert loader.static_data is not None
    assert [asset.asset_id for asset in loader.static_data.assets] == ["community-1"]
    assert [resource.resource_id for resource in loader.static_data.resources] == ["engine-1"]


def test_loader_preserves_observation_only_schema_v1_compatibility() -> None:
    assert ReplayLoader(FIXTURE_PACKAGE).static_data is None
```

Also copy a current builder output containing only the two provenance maps and assert `static_data is None`; this keeps Task 2 independently green before Task 3 changes the builder. For a partial entity group, add only `resources.json` plus its correct manifest hash and assert `ReplayPackageCorrupt("missing required static file: static_data_versions.json")`. Corrupt one static file after hashing and assert the existing generic hash mismatch occurs before static JSON parsing.

For a complete package, independently remove the `nasa_firms` version and
citation entries and assert these stable errors after observation parsing:

```python
"missing static data version for observation source: nasa_firms"
"missing source citation for observation source: nasa_firms"
```

- [ ] **Step 2: Run the loader tests and verify RED**

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_loader.py -q
```

Expected: new assertions fail because `ReplayLoader` has no `static_data` attribute and does not parse the group.

- [ ] **Step 3: Integrate the parser without changing observation semantics**

After the existing loop has hash-verified every manifest file into `file_contents`, add:

```python
entity_static_present = any(
    filename in file_contents
    for filename in ("exposed_assets.geojson", "resources.json")
)
if entity_static_present:
    static_files = {
        filename: file_contents[filename]
        for filename in STATIC_DATA_FILENAMES
        if filename in file_contents
    }
    try:
        self.static_data = parse_replay_static_data(static_files, self.manifest)
    except ReplayStaticDataInvalid as error:
        raise ReplayPackageCorrupt(str(error)) from error
else:
    self.static_data = None
```

Keep this after all file hashes are verified and before observation records are accepted. While parsing observations, collect `observation.source_name` values. After every observation has passed the existing scope and duplicate-identity checks, require each collected source in both static provenance maps when `self.static_data` is not `None`:

```python
for source_name in sorted(observation_sources):
    if source_name not in self.static_data.static_data_versions:
        raise ReplayPackageCorrupt(
            f"missing static data version for observation source: {source_name}"
        )
    if source_name not in self.static_data.source_citations:
        raise ReplayPackageCorrupt(
            f"missing source citation for observation source: {source_name}"
        )
```

Do not retain a second copy of static file bytes after construction, and do not alter `iter_until`.

- [ ] **Step 4: Run loader, replay, and graph regression tests**

Run:

```bash
cd backend
uv run pytest tests/unit/replay tests/unit/geospatial/test_road_graph.py -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
```

Expected: all commands exit `0`; observation-only `replay-small` and road-graph publication remain compatible.

- [ ] **Step 5: Commit loader integration**

```bash
git add backend/src/wildfireops/replay/loader.py backend/tests/unit/replay/test_loader.py
git commit -m "feat: load replay static context"
```

---

### Task 3: Build and publish complete canonical replay packages

**Files:**
- Modify: `backend/src/wildfireops/replay/build.py`
- Modify: `backend/tests/unit/replay/test_builder.py`
- Modify: `docs/superpowers/plans/2026-07-16-wildfireops-implementation.md`

**Interfaces:**
- Consumes: Task 1 parser/projection and the existing keyword-only `build_package` API returning `Path`.
- Produces: builder output whose manifest always hashes the two observation files plus the complete four-file static group.

- [ ] **Step 1: Extend the staging fixture and deterministic-output assertions**

In `_staging_directory`, write the same valid `exposed_assets.geojson` and `resources.json` payloads used by Task 1. Change metadata to:

```python
{
    "algorithm_config_version": "test-config-v1",
    "static_data_versions": {
        "census": "2023-acs5",
        "nasa_firms": "recorded-test-v1",
        "nws": "recorded-test-v1",
        "simulated_resources": "synthetic-v1",
    },
    "source_citations": {
        "census": "https://www.census.gov/",
        "simulated_resources": "WildfireOps portfolio simulation",
        "nasa_firms": "https://firms.modaps.eosdis.nasa.gov/",
        "nws": "https://www.weather.gov/documentation/services-web-api",
    },
}
```

Update the deterministic builder test to assert both builds are byte-for-byte identical, `manifest.files` contains exactly:

```python
{
    "fire_detections.jsonl",
    "weather_observations.jsonl",
    "static_data_versions.json",
    "source_citations.json",
    "exposed_assets.geojson",
    "resources.json",
}
```

Assert `ReplayLoader(output).static_data` is populated, features/resources are sorted, resource capabilities are sorted, every manifest digest matches the published bytes, and no staging-only `metadata.json` is copied.

- [ ] **Step 2: Add focused builder failure tests and verify RED**

Test both missing staged entity files and one representative parser failure (for example malformed GeoJSON), asserting `ReplayBuildError` preserves the filename/context. Task 1 already owns the exhaustive parser-invariant matrix.

Add a separate post-temporary-directory cleanup test. Monkeypatch
`wildfireops.replay.build.ReplayLoader` to raise
`ReplayPackageCorrupt("injected final validation failure")`, call the builder,
then assert the output does not exist and
`list(output.parent.glob(f".{output.name}.tmp-*")) == []`. This proves cleanup
after `mkdtemp`, rather than only failures that occur while reading staged input.

Run:

```bash
cd backend
uv run pytest tests/unit/replay/test_builder.py -q
```

Expected: new complete-output assertions fail because the builder does not read or emit assets/resources.

- [ ] **Step 3: Extend the builder minimally**

Add the two new output filenames and build a raw static file mapping from metadata plus staged files:

```python
raw_static_files = {
    "static_data_versions.json": _canonical_json(metadata.static_data_versions),
    "source_citations.json": _canonical_json(metadata.source_citations),
    "exposed_assets.geojson": _read_staged_file(source_dir, "exposed_assets.geojson"),
    "resources.json": _read_staged_file(source_dir, "resources.json"),
}
try:
    static_data = parse_replay_static_data(raw_static_files, manifest_template)
except ReplayStaticDataInvalid as error:
    raise ReplayBuildError(str(error)) from error
contents.update(
    {
        filename: _canonical_json(payload)
        for filename, payload in static_data_payloads(static_data).items()
    }
)
```

Keep the existing atomic temporary-directory publication and final `ReplayLoader(temporary)` verification. Update `--source-dir` help to name the two required staged static files and state that credentials/raw acquisition downloads stay outside the output package.

- [ ] **Step 4: Correct the parent Task 14 offline workflow**

Update Task 14 Step 1 in
`docs/superpowers/plans/2026-07-16-wildfireops-implementation.md` so it no
longer implies that the package builder downloads source data or uses a
nonexistent validation module. State that acquisition and normalization happen
outside the committed package, credentials are never passed to the builder, and
require these staged inputs:

```text
fire_detections.jsonl
weather_observations.jsonl
metadata.json
exposed_assets.geojson
resources.json
```

Add the builder-produced `static_data_versions.json` and
`source_citations.json` to Task 14's package file list; their source maps remain
fields inside staged `metadata.json`, rather than duplicate staged files.

Replace the command with the actual credential-free boundary:

```bash
cd backend
uv run python -m wildfireops.replay.build \
  --source-dir ../data/staging/park-fire \
  --package-id park-fire-2024-v1 \
  --bbox=-122.40,39.20,-120.30,41.00 \
  --start 2024-07-24T00:00:00Z \
  --end 2024-08-02T00:00:00Z \
  --output ../data/replay/park-fire
```

The builder's final `ReplayLoader(temporary)` call is the package validation;
remove `python -m wildfireops.replay.validate`. Also correct Task 14's degraded
allocator expectation: capacity shortage remains a valid deterministic solution
with uncovered destinations, so it must not demand `INFEASIBLE`.

- [ ] **Step 5: Run the complete slice verification**

Run:

```bash
cd backend
uv run pytest tests/unit/replay tests/unit/geospatial/test_road_graph.py -q
uv run pytest tests/unit tests/architecture -q
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
git diff --check
```

Expected: all commands exit `0`; the current unit/architecture baseline is at least `462` tests and may increase only by the new replay tests.

- [ ] **Step 6: Commit complete package construction**

```bash
git add backend/src/wildfireops/replay/build.py backend/tests/unit/replay/test_builder.py docs/superpowers/plans/2026-07-16-wildfireops-implementation.md
git commit -m "feat: build complete replay packages"
```

---

## Final review gate

Before publication, a fresh reviewer must compare the complete slice against this plan and inspect:

- strict all-or-none static grouping and hash-before-parse ordering;
- canonical output determinism and stable IDs;
- source/version/citation truthfulness;
- demand metadata compatibility with `decision/recommendations.py`;
- simulated-resource labeling;
- geometry validity and manifest-bbox containment;
- schema-v1 observation-only compatibility;
- atomic builder cleanup and absence of credentials/acquisition artifacts;
- no unnecessary abstraction or dependency.

Any finding receives a focused RED regression, a minimal fix commit, the full slice verification, and re-review before push.
