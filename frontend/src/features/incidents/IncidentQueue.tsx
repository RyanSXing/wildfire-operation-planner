import type { IncidentSummary } from "../../api/types";
import { FreshnessBadge } from "./FreshnessBadge";

interface IncidentQueueProps {
  incidents: readonly IncidentSummary[];
  selectedIncidentId: string | null;
  onSelect: (incidentId: string) => void;
}

const observedAtFormatter = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

export function IncidentQueue({
  incidents,
  selectedIncidentId,
  onSelect,
}: IncidentQueueProps) {
  return (
    <aside className="incident-rail" aria-labelledby="incident-queue-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Observe</p>
          <h2 id="incident-queue-heading">Incident queue</h2>
        </div>
        <span className="incident-count">{incidents.length}</span>
      </div>

      {incidents.length === 0 ? (
        <p className="empty-state">No active incidents are available.</p>
      ) : (
        <div className="incident-list">
          {incidents.map((incident) => (
            <button
              type="button"
              className="incident-row"
              aria-pressed={incident.id === selectedIncidentId}
              key={incident.id}
              onClick={() => onSelect(incident.id)}
            >
              <span className="incident-row__title">{incident.name}</span>
              <span className="incident-row__risk">{incident.risk.score}</span>
              <span className="incident-row__meta">
                <span>{incident.exposedAssetCount} exposed</span>
                <FreshnessBadge freshness={incident.freshness} />
              </span>
              <time dateTime={incident.lastObservedAt}>
                Observed {observedAtFormatter.format(new Date(incident.lastObservedAt))} UTC
              </time>
            </button>
          ))}
        </div>
      )}

      <p className="simulation-legend">
        Resource locations shown on the map are simulated.
      </p>
    </aside>
  );
}
