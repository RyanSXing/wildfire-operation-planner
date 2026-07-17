import type { Freshness } from "../../api/types";

const PRESENTATION: Record<Freshness, { label: string; symbol: string }> = {
  fresh: { label: "Fresh", symbol: "●" },
  stale: { label: "Stale", symbol: "▲" },
  unavailable: { label: "Unavailable", symbol: "×" },
};

interface FreshnessBadgeProps {
  freshness: Freshness;
}

export function FreshnessBadge({ freshness }: FreshnessBadgeProps) {
  const presentation = PRESENTATION[freshness];
  return (
    <span className={`freshness-badge freshness-badge--${freshness}`}>
      <span aria-hidden="true">{presentation.symbol}</span>
      {presentation.label}
    </span>
  );
}
