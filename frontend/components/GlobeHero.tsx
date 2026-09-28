"use client";

import Link from "next/link";
import { Signal } from "@/lib/api";
import { signalsToFlights } from "@/lib/globe";
import GlobeCanvas from "./GlobeCanvas";

export default function GlobeHero({ signals }: { signals: Signal[] }) {
  const flights = signalsToFlights(signals);
  const hot = [...flights].sort((a, b) => b.norm - a.norm).slice(0, 4);

  return (
    <>
      <div className="panel" style={{ padding: "22px 24px", marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Welcome to Oracle X</h1>
        <p style={{ fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.65, marginTop: 8, maxWidth: 640 }}>
          Oracle X is an autonomous quant engine: a chain of specialized agents that scan cross-asset order
          flow, trace the causal story behind a move, and pass only the ideas that clear a hard risk gate.
          The map below plots live signals from the pipeline across global exchanges — drag to rotate.
        </p>
      </div>

      <div style={{ position: "relative", height: 300, borderRadius: 16, border: "1px solid var(--border)", overflow: "hidden", background: "#03060d", marginBottom: 20 }}>
        <GlobeCanvas flights={flights} />
        {flights.length === 0 ? (
          <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--text-muted)" }}>
            No signals ingested yet
          </div>
        ) : (
          <div
            className="mono"
            style={{
              position: "absolute", top: 12, left: 12, right: 12, fontSize: 10.5,
              background: "rgba(8,13,24,0.82)", border: "1px solid var(--border)", padding: "7px 12px",
              borderRadius: 9, backdropFilter: "blur(10px)", pointerEvents: "none", whiteSpace: "nowrap",
              overflow: "hidden", textOverflow: "ellipsis",
            }}
          >
            <span style={{ color: "var(--text-muted)" }}>LIVE FLOW &nbsp;</span>
            {hot.map((f, i) => (
              <span key={f.id}>
                <span style={{ fontWeight: 700, color: f.direction === "LONG" ? "var(--long)" : "var(--short)" }}>
                  {f.label} {f.changeLabel}
                </span>
                {i < hot.length - 1 && <span style={{ color: "var(--text-muted)", margin: "0 8px" }}>·</span>}
              </span>
            ))}
          </div>
        )}
        <Link
          href="/flight-radar"
          style={{
            position: "absolute", bottom: 12, right: 12, fontSize: 11, fontWeight: 600, color: "#04130c",
            background: "linear-gradient(135deg, #0fdc85, #0f6b4d)", padding: "8px 14px", borderRadius: 9,
            boxShadow: "0 0 18px -4px var(--signal-glow)", textDecoration: "none",
          }}
        >
          Open full Flight Radar →
        </Link>
      </div>
    </>
  );
}
