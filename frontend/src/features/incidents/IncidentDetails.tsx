import type { ReactNode } from "react";

import type {
  ExposedAsset,
  IncidentDetail,
  JsonValue,
  Risk,
  SimulatedResource,
} from "../../api/types";
import { FreshnessBadge } from "./FreshnessBadge";

export type RiskContext = "Current snapshot" | "Replay frame";

export type IncidentDetailsProps = {
  incident: IncidentDetail;
  visualizedRisk: Risk;
  riskContext: RiskContext;
  children?: ReactNode;
};

const numberFormatter = new Intl.NumberFormat("en-CA", {
  maximumFractionDigits: 3,
});

export function IncidentDetails({
  incident,
  visualizedRisk,
  riskContext,
  children,
}: IncidentDetailsProps) {
  const topDriver = highestContribution(visualizedRisk);

  return (
    <article className="decision-workspace" aria-labelledby="decision-workspace-heading">
      <header className="decision-workspace__header">
        <h2 id="decision-workspace-heading">Decision workspace</h2>
      </header>

      <section className="decision-workspace__section" aria-label="Incident overview">
        <h3>Incident overview</h3>
        <p className="decision-workspace__incident-name">{incident.name}</p>
        <dl className="decision-workspace__metrics">
          <dt>Status</dt>
          <dd>{incident.status}</dd>
          <dt>Freshness</dt>
          <dd>
            <FreshnessBadge freshness={incident.freshness} />
          </dd>
          <dt>Priority score</dt>
          <dd>{formatNumber(visualizedRisk.score)} <ContextLabel label={riskContext} /></dd>
        </dl>
        <p className="decision-workspace__driver-summary">
          {topDriver
            ? `Top driver: ${formatLabel(topDriver.name)} contributed ${formatNumber(topDriver.contribution)} points.`
            : "No priority drivers are available."}
        </p>
        <div className="decision-workspace__timestamps">
          <time dateTime={incident.firstObservedAt}>
            First observed {formatUtc(incident.firstObservedAt)}
          </time>
          <time dateTime={incident.lastObservedAt}>
            Last observed {formatUtc(incident.lastObservedAt)}
          </time>
        </div>
      </section>

      {children}

      <details className="decision-workspace__section decision-workspace__disclosure">
        <summary>
          <span>Risk evidence</span>
          <span>{pluralize(visualizedRisk.contributions.length, "factor")}</span>
        </summary>
        <section className="decision-workspace__disclosure-content" aria-label="Risk explanation">
          <div className="decision-workspace__section-heading">
            <h3>Risk explanation</h3>
            <ContextLabel label={riskContext} />
          </div>
          <dl className="decision-workspace__metrics">
            <dt>Priority score</dt>
            <dd>{formatNumber(visualizedRisk.score)}</dd>
            <dt>Algorithm</dt>
            <dd>{visualizedRisk.algorithmVersion}</dd>
          </dl>

          {visualizedRisk.contributions.length === 0 ? (
            <p className="decision-workspace__empty">
              No risk factors are available.
            </p>
          ) : (
            <ul className="risk-factor-list" aria-label="Risk factors">
              {visualizedRisk.contributions.map((factor) => (
                <li className="risk-factor" key={factor.name}>
                  <h4>{factor.name}</h4>
                  <dl className="risk-factor__metrics">
                    <dt>Normalized value</dt>
                    <dd>{formatNumber(factor.normalizedValue)}</dd>
                    <dt>Weight</dt>
                    <dd>{formatNumber(factor.weight)}</dd>
                    <dt>Contribution</dt>
                    <dd>{formatNumber(factor.contribution)}</dd>
                  </dl>
                  <details>
                    <summary>Raw evidence</summary>
                    <pre className="decision-workspace__evidence">
                      {formatJson(factor.rawValue)}
                    </pre>
                  </details>
                </li>
              ))}
            </ul>
          )}

          <details className="decision-workspace__subsection">
            <summary>Detailed model configuration</summary>
            <div className="decision-workspace__section-heading">
              <h4>Model configuration</h4>
              <ContextLabel label="Current snapshot" />
            </div>
            <pre className="decision-workspace__evidence">
              {formatJson(incident.risk.configuration)}
            </pre>
          </details>
        </section>
      </details>

      <details className="decision-workspace__section decision-workspace__disclosure">
        <summary>
          <span>Source provenance</span>
          <span>{detectionSummary(incident)}</span>
        </summary>
        <section className="decision-workspace__disclosure-content" aria-label="Source provenance">
          <div className="decision-workspace__section-heading">
            <h3>Detection provenance</h3>
            <ContextLabel label="Current snapshot" />
          </div>
          <details>
            <summary>Source versions</summary>
            <pre className="decision-workspace__evidence">
              {formatJson(incident.sourceVersions)}
            </pre>
          </details>
          {incident.detections.length === 0 ? (
            <p className="decision-workspace__empty">
              No detection provenance is available.
            </p>
          ) : (
            <ul className="provenance-list" aria-label="Detection provenance">
              {incident.detections.map((detection) => (
                <li
                  className="provenance-list__item"
                  key={`${detection.sourceName}:${detection.sourceRecordId}`}
                >
                  <h5>{sourceLabel(detection.sourceName)}</h5>
                  <dl>
                    <dt>Source record</dt>
                    <dd>{detection.sourceRecordId}</dd>
                    <dt>Observed</dt>
                    <dd>
                      <time dateTime={detection.observedAt}>
                        Observed {formatUtc(detection.observedAt)}
                      </time>
                    </dd>
                    <dt>Confidence</dt>
                    <dd>{formatNumber(detection.confidence)}</dd>
                    <dt>Intensity</dt>
                    <dd>{formatOptionalNumber(detection.intensity)}</dd>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </section>
      </details>

      <details className="decision-workspace__section decision-workspace__disclosure">
        <summary>
          <span>Exposed assets</span>
          <span>{pluralize(incident.exposedAssets.length, "exposed asset")}</span>
        </summary>
        <section className="decision-workspace__disclosure-content" aria-label="Exposed assets">
          <div className="decision-workspace__section-heading">
            <h3>Exposed assets</h3>
            <ContextLabel label="Current snapshot" />
          </div>
          {incident.exposedAssets.length === 0 ? (
            <p className="decision-workspace__empty">
              No exposed assets are available.
            </p>
          ) : (
            <ul className="asset-list" aria-label="Exposed assets">
              {incident.exposedAssets.map((asset) => (
                <AssetItem asset={asset} key={asset.assetId} />
              ))}
            </ul>
          )}
        </section>
      </details>

      <details className="decision-workspace__section decision-workspace__disclosure">
        <summary>
          <span>Simulated resources</span>
          <span>{pluralize(incident.simulatedResources.length, "simulated resource")}</span>
        </summary>
        <section className="decision-workspace__disclosure-content" aria-label="Simulated resources">
          <div className="decision-workspace__section-heading">
            <h3>Simulated resources</h3>
            <ContextLabel label="Current snapshot" />
          </div>
          {incident.simulatedResources.length === 0 ? (
            <p className="decision-workspace__empty">
              No simulated resources are available.
            </p>
          ) : (
            <ul className="resource-list" aria-label="Simulated resources">
              {incident.simulatedResources.map((resource) => (
                <ResourceItem resource={resource} key={resource.resourceId} />
              ))}
            </ul>
          )}
        </section>
      </details>
    </article>
  );
}

function AssetItem({ asset }: { asset: ExposedAsset }) {
  return (
    <li className="asset-list__item">
      <h4>{asset.name}</h4>
      <dl>
        <dt>Kind</dt>
        <dd>{asset.assetKind}</dd>
        <dt>Distance</dt>
        <dd>{formatNumber(asset.distanceMeters)} m</dd>
        <dt>Bearing</dt>
        <dd>
          {asset.bearingDegrees === null
            ? "Not reported"
            : `${formatNumber(asset.bearingDegrees)}°`}
        </dd>
        <dt>Population</dt>
        <dd>{formatOptionalNumber(asset.population)}</dd>
        <dt>Capacity</dt>
        <dd>{formatOptionalNumber(asset.capacity)}</dd>
        <dt>Source</dt>
        <dd>{asset.sourceName ?? "Not reported"}</dd>
        <dt>Version</dt>
        <dd>{asset.sourceVersion ?? "Not reported"}</dd>
      </dl>
    </li>
  );
}

function ResourceItem({ resource }: { resource: SimulatedResource }) {
  return (
    <li className="resource-list__item">
      <div className="resource-list__heading">
        <h4>{resource.resourceType}</h4>
        <span className="simulation-label">Simulated</span>
      </div>
      <dl>
        <dt>Capabilities</dt>
        <dd>
          {resource.capabilities.length > 0
            ? resource.capabilities.join(", ")
            : "None reported"}
        </dd>
        <dt>Capacity</dt>
        <dd>{formatNumber(resource.capacity)}</dd>
        <dt>Status</dt>
        <dd>{resource.status}</dd>
        <dt>Availability</dt>
        <dd>{resource.available ? "Available" : "Unavailable"}</dd>
      </dl>
    </li>
  );
}

function ContextLabel({ label }: { label: RiskContext }) {
  return <span className="snapshot-context">{label}</span>;
}

function formatJson(value: JsonValue): string {
  return JSON.stringify(value, null, 2);
}

function formatNumber(value: number): string {
  return numberFormatter.format(value);
}

function formatOptionalNumber(value: number | null): string {
  return value === null ? "Not reported" : formatNumber(value);
}

function formatUtc(timestamp: string): string {
  return `${new Date(timestamp).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function highestContribution(risk: Risk): Risk["contributions"][number] | undefined {
  return risk.contributions.reduce<Risk["contributions"][number] | undefined>(
    (highest, factor) =>
      !highest || factor.contribution > highest.contribution ? factor : highest,
    undefined,
  );
}

function formatLabel(value: string): string {
  const words = value.replaceAll("_", " ").trim().toLowerCase();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : value;
}

function sourceLabel(sourceName: string): string {
  return sourceName
    .split("_")
    .filter(Boolean)
    .map((word) =>
      ["firms", "nasa", "ncei", "noaa"].includes(word.toLowerCase())
        ? word.toUpperCase()
        : formatLabel(word),
    )
    .join(" ");
}

function detectionSummary(incident: IncidentDetail): string {
  const count = incident.detections.length;
  const sources = [...new Set(incident.detections.map(({ sourceName }) => sourceLabel(sourceName)))];
  if (count === 0) {
    return "No detections";
  }
  if (sources.length === 1) {
    return `${count} ${sources[0]} ${count === 1 ? "detection" : "detections"}`;
  }
  return `${pluralize(count, "detection")} from ${sources.join(", ")}`;
}

function pluralize(count: number, label: string): string {
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}
