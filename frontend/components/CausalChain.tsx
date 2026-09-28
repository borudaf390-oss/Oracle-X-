"use client";

import { Signal } from "@/lib/api";

function fmtPct(v: number | null) {
  if (v === null || v === undefined) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

export default function CausalChain({ signal }: { signal: Signal }) {
  const reason = signal.reason || {};
  const leader = reason.leader_symbol as string | undefined;
  const leaderMove = reason.leader_move_pct as number | undefined;
  const correlation = reason.correlation as number | undefined;
  const band = reason.band as string | undefined;

  const steps = [
    leader ? { label: leader, sub: fmtPct(leaderMove ?? null), kind: "event" as const } : null,
    correlation !== undefined
      ? { label: "Propagation", sub: `${(correlation * 100).toFixed(0)}% correlated`, kind: "mid" as const }
      : null,
    { label: signal.asset, sub: fmtPct(signal.current_move_pct), kind: "mid" as const },
    { label: "Displacement", sub: fmtPct(signal.displacement_pct), kind: "mid" as const },
    { label: `Opportunity — ${Math.round(signal.alpha_score)}/100`, sub: band ?? signal.direction, kind: "result" as const },
  ].filter(Boolean) as { label: string; sub: string; kind: "event" | "mid" | "result" }[];

  return (
    <div className="chain">
      {steps.map((step, i) => (
        <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div className={`chain-step ${step.kind} mono`}>
            <div>{step.label}</div>
            <div className="sub">{step.sub}</div>
          </div>
          {i < steps.length - 1 && <div className="chain-connector" />}
        </div>
      ))}
    </div>
  );
}
