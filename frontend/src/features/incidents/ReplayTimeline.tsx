export type ReplayTimelineProps = {
  startTime: string | null;
  currentTime: string | null;
  endTime: string | null;
  playing: boolean;
  onSeek: (timestamp: string) => void;
  onPlayChange: (playing: boolean) => void;
};

type UsableRange = {
  start: number;
  current: number;
  end: number;
};

export function ReplayTimeline({
  startTime,
  currentTime,
  endTime,
  playing,
  onSeek,
  onPlayChange,
}: ReplayTimelineProps) {
  const range = usableRange(startTime, currentTime, endTime);
  const currentLabel = range ? formatUtc(range.current) : "Replay unavailable";

  return (
    <section className="replay-timeline" aria-label="Incident replay timeline">
      <div className="replay-timeline__controls">
        <button
          type="button"
          className="replay-timeline__play-control"
          aria-pressed={playing}
          disabled={!range}
          onClick={() => onPlayChange(!playing)}
        >
          {playing ? "Pause" : "Play"}
        </button>

        <label className="replay-timeline__range-label">
          <span>Replay position</span>
          <input
            className="replay-timeline__range"
            type="range"
            min={range?.start ?? 0}
            max={range?.end ?? 1}
            value={range?.current ?? 0}
            step={1000}
            disabled={!range}
            aria-valuetext={currentLabel}
            onChange={(event) => {
              if (range) {
                onSeek(new Date(Number(event.currentTarget.value)).toISOString());
              }
            }}
          />
        </label>
      </div>

      {range ? (
        <>
          <time
            className="replay-timeline__current"
            dateTime={new Date(range.current).toISOString()}
          >
            Current {currentLabel}
          </time>
          <div className="replay-timeline__endpoints">
            <time dateTime={new Date(range.start).toISOString()}>
              Start {formatUtc(range.start)}
            </time>
            <time dateTime={new Date(range.end).toISOString()}>
              End {formatUtc(range.end)}
            </time>
          </div>
        </>
      ) : (
        <>
          <p className="replay-timeline__empty">Replay unavailable.</p>
          <div className="replay-timeline__endpoints">
            <span>Start unavailable</span>
            <span>End unavailable</span>
          </div>
        </>
      )}
    </section>
  );
}

function usableRange(
  startTime: string | null,
  currentTime: string | null,
  endTime: string | null,
): UsableRange | undefined {
  const start = parseTime(startTime);
  const current = parseTime(currentTime);
  const end = parseTime(endTime);

  if (start === undefined || current === undefined || end === undefined || start >= end) {
    return undefined;
  }

  return {
    start,
    current: Math.min(end, Math.max(start, current)),
    end,
  };
}

function parseTime(timestamp: string | null): number | undefined {
  if (!timestamp) {
    return undefined;
  }
  const value = Date.parse(timestamp);
  return Number.isFinite(value) ? value : undefined;
}

function formatUtc(timestamp: number): string {
  return `${new Date(timestamp).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}
