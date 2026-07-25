import type { ExerciseMetadata } from "../api/exerciseTypes";
import { assetKindLabel } from "./language";

export type IntroPanelProps = {
  metadata: ExerciseMetadata;
  starting: boolean;
  error: string | null;
  onStart: () => void;
};

/**
 * Deliverable 1: nobody reaches a decision screen without first being told what
 * is real, what is invented, and that none of it is safe to act on.
 */
export function IntroPanel({
  metadata,
  starting,
  error,
  onStart,
}: IntroPanelProps) {
  const historical = metadata.assets.filter(
    (asset) => asset.provenance === "historical",
  );
  const simulated = metadata.resources.filter(
    (resource) => resource.provenance === "exercise",
  );

  return (
    <div className="wf-centre">
      <main className="wf-sheet" aria-labelledby="wf-intro-title">
        <p className="wf-sheet__eyebrow">TRAINING EXERCISE · NOT AN OPERATIONAL SYSTEM</p>
        <h1 className="wf-sheet__title" id="wf-intro-title">
          {metadata.name}
        </h1>
        <p className="wf-sheet__lede">{metadata.description}</p>

        <div className="wf-note" data-tone="alert" style={{ marginTop: 20 }}>
          <strong>Read this before you start</strong>
          {metadata.safetyStatement}
        </div>

        <h2 className="wf-section" style={{ marginTop: 24 }}>
          WHAT YOU WILL DO
        </h2>
        <ol className="wf-stack" style={{ margin: 0, paddingLeft: 18 }}>
          <li className="wf-prose">
            Pick an objective. It decides how the planner ranks competing work.
          </li>
          <li className="wf-prose">
            Work through {metadata.checkpointCount} checkpoints. The situation
            changes between them, and the exercise explains every change.
          </li>
          <li className="wf-prose">
            There are never enough units. You will have to leave something
            uncovered and say why.
          </li>
          <li className="wf-prose">
            Sign off with your name and a written reason. Everything you do is
            recorded in an audit trail you can read afterwards.
          </li>
        </ol>

        <h2 className="wf-section" style={{ marginTop: 24 }}>
          WHERE THE DATA COMES FROM
        </h2>
        <dl className="wf-kv">
          <div>
            <dt>Real and historical</dt>
            <dd>
              The July 2024 Park Fire satellite detections, NOAA weather
              observations, and the {historical.length} real places below —
              towns, a hospital, a substation, a broadcast site, and a road
              corridor — with their published sources.
            </dd>
          </div>
          <div>
            <dt>Invented for training</dt>
            <dd>
              All {simulated.length} response units, every task and its priority,
              the spot fire at the second checkpoint, the road closure, and the
              shelter field report. None of these happened.
            </dd>
          </div>
          <div>
            <dt>Replay package</dt>
            <dd>
              {metadata.exerciseId} v{metadata.version} — a fixed snapshot, so
              the same choices always produce the same plan.
            </dd>
          </div>
        </dl>

        <h2 className="wf-section" style={{ marginTop: 20 }}>
          REAL PLACES USED IN THIS EXERCISE
        </h2>
        <dl className="wf-kv">
          {historical.map((asset) => (
            <div key={asset.assetId}>
              <dt>{asset.name}</dt>
              <dd>
                {assetKindLabel(asset.assetKind)} · {asset.sourceName} ·{" "}
                <a href={asset.citationUrl} target="_blank" rel="noreferrer">
                  source
                </a>
              </dd>
            </div>
          ))}
        </dl>

        {error !== null && (
          <p className="wf-error" role="alert">
            {error}
          </p>
        )}

        <div className="wf-actions">
          <button
            type="button"
            className="wf-primary"
            onClick={onStart}
            disabled={starting}
          >
            {starting ? "Starting…" : "I understand — start the exercise"}
          </button>
          <a className="wf-dock__hint" href="/monitor">
            Open the Live Monitor instead
          </a>
        </div>
      </main>
    </div>
  );
}
