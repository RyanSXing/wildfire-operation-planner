import { AuditDrawer } from "../features/decisions/AuditDrawer";
import { FreshnessBadge } from "../features/incidents/FreshnessBadge";
import { ScenarioComparison } from "../features/scenarios/ScenarioComparison";
import type {
  IncidentDetail,
  Recommendation,
  ScenarioVersion,
  SourceStatus,
} from "../api/types";
import {
  coverageLine,
  formatDistance,
  formatMinutes,
  humanize,
  labelFor,
  solverPlain,
  versionChanges,
} from "./language";
import { MONITOR_TABS, type MonitorTab } from "./monitorTabs";

export type MonitorDrawerProps = {
  tab: MonitorTab;
  onTabChange: (tab: MonitorTab) => void;
  incident: IncidentDetail;
  recommendation: Recommendation | null;
  baselineOutcome: Recommendation["outcome"] | null;
  version: ScenarioVersion | null;
  resourceLabels: Readonly<Record<string, string>>;
  roadNames: ReadonlyMap<string, string>;
  sources: readonly SourceStatus[];
  selectedId: string | null;
  onLocate: (kind: "asset" | "resource", id: string) => void;
};

export function MonitorDrawer({
  tab,
  onTabChange,
  incident,
  recommendation,
  baselineOutcome,
  version,
  resourceLabels,
  roadNames,
  sources,
  selectedId,
  onLocate,
}: MonitorDrawerProps) {
  const destinationLabels = Object.fromEntries(
    incident.exposedAssets.map(({ assetId, name }) => [assetId, name]),
  );

  return (
    <aside className="wf-drawer" aria-label="Incident details">
      <div className="wf-drawer__head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className="wf-drawer__title">{incident.name}</h2>
          <p className="wf-drawer__meta">
            {incident.status} · {incident.exposedAssets.length} exposed ·{" "}
            {incident.simulatedResources.length} units
          </p>
        </div>
      </div>
      <div className="wf-tabs" role="tablist" aria-label="Incident detail">
        {MONITOR_TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            role="tab"
            id={`wf-monitor-tab-${entry.id}`}
            className="wf-tab"
            aria-selected={tab === entry.id}
            aria-controls={`wf-monitor-panel-${entry.id}`}
            onClick={() => onTabChange(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div
        className="wf-drawer__body"
        role="tabpanel"
        id={`wf-monitor-panel-${tab}`}
        aria-labelledby={`wf-monitor-tab-${tab}`}
        tabIndex={0}
      >
        {tab === "plan" && (
          <PlanTab
            recommendation={recommendation}
            baselineOutcome={baselineOutcome}
            version={version}
            resourceLabels={resourceLabels}
            destinationLabels={destinationLabels}
            roadNames={roadNames}
          />
        )}
        {tab === "resources" && (
          <ResourcesTab
            incident={incident}
            recommendation={recommendation}
            resourceLabels={resourceLabels}
            selectedId={selectedId}
            onLocate={onLocate}
          />
        )}
        {tab === "evidence" && (
          <EvidenceTab
            incident={incident}
            recommendation={recommendation}
            sources={sources}
          />
        )}
        {tab === "audit" &&
          (recommendation ? (
            <AuditDrawer
              key={`audit:${recommendation.id}`}
              recommendationId={recommendation.id}
            />
          ) : (
            <p className="wf-prose wf-prose--muted">
              Nothing is recorded until a plan is approved.
            </p>
          ))}
      </div>
    </aside>
  );
}

function PlanTab({
  recommendation,
  baselineOutcome,
  version,
  resourceLabels,
  destinationLabels,
  roadNames,
}: {
  recommendation: Recommendation | null;
  baselineOutcome: Recommendation["outcome"] | null;
  version: ScenarioVersion | null;
  resourceLabels: Readonly<Record<string, string>>;
  destinationLabels: Readonly<Record<string, string>>;
  roadNames: ReadonlyMap<string, string>;
}) {
  if (!recommendation) {
    return (
      <p className="wf-prose wf-prose--muted">
        No plan yet. Create the baseline from the command bar below the map, then
        adjust the scenario and plan again to compare.
      </p>
    );
  }

  const solver = solverPlain(recommendation);
  const changes = version
    ? versionChanges(version, roadNames, resourceLabels)
    : [];

  return (
    <>
      <h3 className="wf-section">WHAT THE PLAN DOES</h3>
      <div className="wf-note" data-tone={solver.tone}>
        <strong>{coverageLine(recommendation)}</strong>
        {solver.plain}
      </div>

      {changes.length > 0 && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            ASSUMPTIONS THIS PLAN USED
          </h3>
          <div className="wf-stack">
            {changes.map((change) => (
              <div className="wf-note" data-tone="neutral" key={change}>
                {change}
              </div>
            ))}
          </div>
        </>
      )}

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        ASSIGNMENTS
      </h3>
      <div className="wf-stack">
        {recommendation.assignments.map((assignment) => (
          <article
            className="wf-card"
            key={`${assignment.resourceId}-${assignment.destinationId}`}
          >
            <div className="wf-card__head">
              <span className="wf-card__name">
                {labelFor(resourceLabels, assignment.resourceId)}
              </span>
              <span className="wf-card__eta">
                {formatMinutes(assignment.travelMinutes)}
              </span>
            </div>
            <p className="wf-card__task">
              {labelFor(destinationLabels, assignment.destinationId)}
            </p>
            <p className="wf-card__meta">
              {assignment.route.status === "reachable"
                ? formatDistance(assignment.route.distanceMeters)
                : "No route — the planner could not reach this destination"}
            </p>
          </article>
        ))}
        {recommendation.assignments.length === 0 && (
          <p className="wf-prose wf-prose--muted">
            The planner assigned nothing.
          </p>
        )}
      </div>

      {recommendation.uncoveredDestinationIds.length > 0 && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            LEFT UNCOVERED
          </h3>
          <div className="wf-stack">
            {recommendation.uncoveredDestinationIds.map((destinationId) => (
              <div className="wf-note" data-tone="alert" key={destinationId}>
                <strong>{labelFor(destinationLabels, destinationId)}</strong>
                No unit was assigned to this destination.
              </div>
            ))}
          </div>
        </>
      )}

      {baselineOutcome && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            AGAINST THE BASELINE
          </h3>
          <div className="wf-scroll-x">
            <ScenarioComparison
              baseline={baselineOutcome}
              scenario={recommendation.outcome}
            />
          </div>
        </>
      )}
    </>
  );
}

function ResourcesTab({
  incident,
  recommendation,
  resourceLabels,
  selectedId,
  onLocate,
}: {
  incident: IncidentDetail;
  recommendation: Recommendation | null;
  resourceLabels: Readonly<Record<string, string>>;
  selectedId: string | null;
  onLocate: (kind: "asset" | "resource", id: string) => void;
}) {
  const assignedTo = new Map(
    (recommendation?.assignments ?? []).map((assignment) => [
      assignment.resourceId,
      assignment.destinationId,
    ]),
  );
  const destinationLabels = Object.fromEntries(
    incident.exposedAssets.map(({ assetId, name }) => [assetId, name]),
  );

  return (
    <>
      <p className="wf-prose wf-prose--muted" style={{ marginBottom: 12 }}>
        Resource locations are simulated. Selecting one highlights it on the map
        — the keyboard equivalent of clicking the plot.
      </p>

      <h3 className="wf-section">UNITS</h3>
      <div className="wf-stack">
        {incident.simulatedResources.map((resource) => (
          <article className="wf-card" key={resource.resourceId}>
            <div className="wf-card__head">
              <span className="wf-card__name">
                {labelFor(resourceLabels, resource.resourceId)}
              </span>
              <span
                className="wf-card__eta"
                style={{ color: resource.available ? "#5fd08a" : "#ff6a3d" }}
              >
                {resource.available ? "AVAILABLE" : "OUT OF SERVICE"}
              </span>
            </div>
            <p className="wf-card__meta">
              {humanize(resource.resourceType)} · {resource.status}
            </p>
            <p className="wf-card__meta">
              {assignedTo.has(resource.resourceId)
                ? `Assigned to ${labelFor(
                    destinationLabels,
                    assignedTo.get(resource.resourceId) ?? "",
                  )}.`
                : "No assignment in the current plan."}
            </p>
            <div className="wf-actions" style={{ marginTop: 10 }}>
              <button
                type="button"
                className="wf-secondary"
                aria-pressed={selectedId === resource.resourceId}
                onClick={() => onLocate("resource", resource.resourceId)}
              >
                Show on map
              </button>
            </div>
          </article>
        ))}
      </div>

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        EXPOSED PLACES
      </h3>
      <div className="wf-stack">
        {incident.exposedAssets.map((asset) => (
          <article className="wf-card" key={asset.assetId}>
            <div className="wf-card__head">
              <span className="wf-card__name">{asset.name}</span>
            </div>
            <p className="wf-card__meta">
              {humanize(asset.assetKind)}
              {asset.population === null
                ? ""
                : ` · ${asset.population.toLocaleString("en-US")} people`}
            </p>
            <div className="wf-actions" style={{ marginTop: 10 }}>
              <button
                type="button"
                className="wf-secondary"
                aria-pressed={selectedId === asset.assetId}
                onClick={() => onLocate("asset", asset.assetId)}
              >
                Show on map
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function EvidenceTab({
  incident,
  recommendation,
  sources,
}: {
  incident: IncidentDetail;
  recommendation: Recommendation | null;
  sources: readonly SourceStatus[];
}) {
  return (
    <>
      <h3 className="wf-section">WHY THIS INCIDENT RANKS WHERE IT DOES</h3>
      <section aria-label="Risk explanation">
        <dl className="wf-kv">
          <div>
            <dt>Priority score</dt>
            <dd>
              {incident.risk.score} · {incident.risk.algorithmVersion}
            </dd>
          </div>
          {incident.risk.contributions.map((contribution) => (
            <div key={contribution.name}>
              <dt>{humanize(contribution.name)}</dt>
              <dd>
                contributed {contribution.contribution} (weight{" "}
                {contribution.weight})
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {recommendation && (
        <>
          <h3 className="wf-section" style={{ marginTop: 20 }}>
            HOW THIS PLAN WAS MADE
          </h3>
          <section aria-label="Solver evidence">
            <dl className="wf-kv">
              <div>
                <dt>Solver status</dt>
                <dd>{recommendation.solverStatus}</dd>
              </div>
              <div>
                <dt>Runtime</dt>
                <dd>{recommendation.runtimeMilliseconds} ms</dd>
              </div>
              <div>
                <dt>Objective value</dt>
                <dd>{recommendation.objectiveComponents.objectiveValue}</dd>
              </div>
              <div>
                <dt>Travel cost</dt>
                <dd>{recommendation.objectiveComponents.travelCost}</dd>
              </div>
              <div>
                <dt>Uncovered risk penalty</dt>
                <dd>
                  {recommendation.objectiveComponents.uncoveredRiskPenalty}
                </dd>
              </div>
              <div>
                <dt>Road graph</dt>
                <dd>{recommendation.graphVersion}</dd>
              </div>
              <div>
                <dt>Risk model</dt>
                <dd>{recommendation.riskVersion}</dd>
              </div>
              <div>
                <dt>Allocation</dt>
                <dd>{recommendation.algorithmVersion}</dd>
              </div>
            </dl>
          </section>
        </>
      )}

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        WHERE THE DATA CAME FROM
      </h3>
      <section aria-label="Source provenance">
        <dl className="wf-kv">
          <div>
            <dt>First observed</dt>
            <dd>{incident.firstObservedAt}</dd>
          </div>
          <div>
            <dt>Last observed</dt>
            <dd>{incident.lastObservedAt}</dd>
          </div>
          <div>
            <dt>Detections</dt>
            <dd>{incident.detections.length} satellite detections</dd>
          </div>
          {Object.entries(incident.sourceVersions).map(([name, version]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{String(version)}</dd>
            </div>
          ))}
        </dl>
      </section>

      <h3 className="wf-section" style={{ marginTop: 20 }}>
        FEED FRESHNESS
      </h3>
      <section aria-label="Source freshness">
        <dl className="wf-kv">
          {sources.map((source) => (
            <div key={source.sourceName}>
              <dt>{source.sourceName}</dt>
              <dd>
                <FreshnessBadge freshness={source.freshness} />
              </dd>
            </div>
          ))}
          {sources.length === 0 && (
            <div>
              <dt>Sources</dt>
              <dd>No source status is available.</dd>
            </div>
          )}
        </dl>
      </section>
    </>
  );
}
