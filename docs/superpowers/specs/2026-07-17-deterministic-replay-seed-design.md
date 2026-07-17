# Deterministic Replay Seed Design

## Goal

Add one credential-free command that loads a validated replay package into an
empty PostGIS database and atomically creates the operational state required by
the WildfireOps UI: static assets, simulated resources, observations, incidents,
exposure snapshots, risk scores, and truthful source freshness.

## Scope

This slice adds:

- `python -m wildfireops.replay.seed PACKAGE`;
- deterministic package and seed-request digests;
- digest-safe idempotent reruns;
- strict refusal to mix replay data with unrelated operational rows;
- one transaction for static data, observations, derived state, and source
  status;
- PostGIS integration proof for success, no-op, conflict, dirty database, and
  rollback.

This slice does not add a migration, HTTP endpoint, replay-mode API startup,
worker behavior, notifications, frontend code, real Park Fire data, a graph
loader, or provenance-map persistence.

## Existing Contracts Reused

- `ReplayLoader` validates the manifest, every referenced file hash, the
  complete static group, observation scope, and observation source provenance.
- `ReplayManifest.to_payload()` provides the stable semantic manifest shape and
  includes attached road-graph metadata when present.
- `ScenarioRepository.claim_idempotency()` already provides transaction-bound
  `(scope, key, request_hash)` claims with row locking.
- `acquire_incident_refresh_lock()` already serializes ingestion and incident
  refresh transactions with a PostgreSQL advisory transaction lock.
- `ObservationRepository.upsert_many()` inserts observations by stable source
  identity.
- `cluster_detections()`, `refresh_incidents()`, and
  `refresh_exposure_and_risk()` remain the only incident, exposure, and risk
  implementations.
- `materialize_json_object()` converts the replay contract's frozen JSON values
  into JSONB-compatible values.

No parallel schema, generic seeding framework, or second derivation pipeline is
introduced.

## Public Interface

The new module is `backend/src/wildfireops/replay/seed.py`.

It exposes:

```python
class ReplaySeedError(ValueError): ...
class ReplaySeedConflict(ReplaySeedError): ...

@dataclass(frozen=True, slots=True)
class ReplaySeedResult:
    package_id: str
    package_digest: str
    status: Literal["seeded", "already_seeded"]
    assets_inserted: int
    resources_inserted: int
    observations_inserted: int
    incidents_created: int
    snapshots_created: int

async def seed_replay_package(
    *,
    loader: ReplayLoader,
    session_factory: SessionFactory,
    clustering_config: ClusteringConfig,
    exposure_config: ExposureConfig,
    risk_config: RiskConfig,
) -> ReplaySeedResult: ...
```

The CLI accepts exactly one positional package directory and reads the existing
database and algorithm settings from `Settings`. Successful output is one JSON
object containing the `ReplaySeedResult` fields. Validation, conflict, dirty
database, or processing errors return a nonzero exit without printing secrets.

## Digest and Idempotency Contract

Two SHA-256 values have distinct meanings:

1. `package_digest` hashes canonical compact JSON from
   `ReplayManifest.to_payload()` with sorted keys. It is independent of manifest
   whitespace and covers package ID, time bounds, file hashes, algorithm label,
   and attached road-graph metadata.
2. `seed_request_hash` hashes canonical compact JSON containing the
   `package_digest` plus every clustering, exposure, and risk configuration
   value used to derive database state.

The database claim uses:

```text
scope = replay_seed
key = manifest.package_id
request_hash = seed_request_hash
```

Claim behavior is:

- a new claim continues with seeding;
- an existing claim with the same request hash returns `already_seeded` with
  zero inserted/created counts;
- an existing claim with a different request hash raises
  `ReplaySeedConflict`;
- a failed transaction rolls back the claim with every other write.

`complete_idempotency()` is unnecessary: the claim and all seeded state commit
in the same transaction, so a committed claim is the completion marker. This
avoids a new replay table and migration.

Changing any package file hash, road graph, time bound, manifest algorithm
label, or runtime derivation setting makes the same package ID conflict instead
of silently producing different state.

## Package Preconditions

`ReplayLoader` is constructed before opening a database transaction. The seed
requires `loader.static_data` to be present; legacy observation-only packages
remain readable but are not seedable into a complete demo.

All observations through `manifest.end_at` are seeded. A package that produces
no incident cluster under the supplied clustering configuration is rejected so
a successful seed always creates usable derived state.

An attached road graph is not required by this slice because it remains a
filesystem input for replay-mode API startup. If present, its manifest metadata
and hash participate in both package and seed identity.

## Atomic Transaction

The service opens one `AsyncSession` transaction and performs these operations
in order:

1. Acquire `acquire_incident_refresh_lock(session)` before inspecting state.
   This serializes replay seeds with ingestion refresh and prevents two distinct
   packages from both observing an empty database.
2. Claim idempotency with `ScenarioRepository(session)`. Return the same-digest
   no-op or reject a changed request before checking database emptiness.
3. For a new claim, require these base tables to contain no rows:
   `source_observations`, `quarantined_observations`, `exposed_assets`,
   `resource_units`, `wildfire_incidents`, and `source_status`.
   Downstream snapshots, scenarios, recommendations, decisions, and audit rows
   cannot exist without these parent records. Existing idempotency rows in other
   scopes are not operational replay data.
4. Insert every replay asset and resource in stable ID order. Convert validated
   GeoJSON to SRID 4326 geometry with the installed Shapely/GeoAlchemy types and
   materialize frozen metadata without changing `raw_metadata.demand` or
   `raw_metadata.simulated`.
5. Insert observations through `ObservationRepository.upsert_many()`. A new
   seed into an empty database must report zero deduplicated observations.
6. Flush, load current detections at `manifest.end_at`, cluster with the supplied
   configuration, and reject an empty cluster result.
7. Call `refresh_incidents()` and `refresh_exposure_and_risk()` in the same
   transaction. The latter may reacquire the same transaction advisory lock.
8. Add one `SourceStatusModel` per actual observation source. Set
   `last_attempted_at` to `manifest.end_at`, `last_success_at` to that source's
   latest observation timestamp, accepted count to its observation count, and
   deduplicated/quarantined counts to zero.
9. Return counts and commit through the transaction context manager.

Any exception rolls back the idempotency claim, static rows, observations,
incidents, snapshots, risk changes, and source statuses together. The seeder
does not write a separate failure status because that would make a failed seed
leave database state.

## Database Ownership Rule

New replay seeds refuse databases containing unrelated operational rows. They
never merge, update, delete, or replace existing assets, resources,
observations, incidents, or statuses.

The identical-package no-op check precedes the emptiness check because a
previous successful seed necessarily leaves operational rows. This design does
not audit or repair manual database tampering after a successful seed; add an
integrity audit only if that becomes an observed need.

## Source and Provenance Semantics

Source status rows use actual names such as `nasa_firms` and `nws`, never the
synthetic adapter name `replay:<package_id>`. Latest source success reflects the
latest recorded observation, while `manifest.end_at` is the replay clock used
to evaluate freshness.

Static source names and versions remain on `ExposedAssetModel`. Full
`static_data_versions` and `source_citations` maps remain in the validated
package for the later replay-mode API slice; this seed does not add database
columns merely to duplicate package metadata.

## CLI and Documentation Flow

Task 14's repeatable command order becomes:

1. build the canonical replay package from staged offline files;
2. attach the road graph;
3. migrate an empty PostGIS database;
4. run `python -m wildfireops.replay.seed ../data/replay/park-fire`;
5. start the later replay-mode API against the same package and database.

The seed command never acquires data, reads live-source credentials, modifies
the replay package, or starts application services.

## Verification

One PostGIS integration test module proves:

- a complete synthetic package creates exact asset/resource/observation counts,
  at least one active incident, immutable snapshots, risk scores, preserved
  demand/simulation metadata, and per-source statuses;
- rerunning the identical package/configuration returns `already_seeded` and
  leaves every row count unchanged;
- the same package ID with changed manifest contents or derivation settings
  raises `ReplaySeedConflict`;
- a different package against unrelated operational data is rejected without
  changing that data;
- an injected incident or exposure refresh failure rolls back the replay claim
  and every seeded row;
- concurrent distinct seeds serialize so only one can own an initially empty
  database.

Focused unit tests cover only pure canonical digest construction and CLI result
serialization. Existing replay, ingestion, exposure, incident, Ruff, mypy, and
full PostGIS suites remain regression gates.

## Deferred Work

- replay-mode API startup and package provenance responses;
- road-graph pinning at process startup;
- semantic golden outputs and degraded-mode proof;
- Playwright demonstration and benchmarks;
- real Park Fire acquisition, historical weather selection, graph curation,
  licensing, and attribution.
