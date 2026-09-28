"use client";

import { useEffect, useState } from "react";
import { api, MarketMapData, Signal } from "@/lib/api";
import MarketMap from "@/components/MarketMap";
import CausalChain from "@/components/CausalChain";

export default function MarketMapPage() {
  const [map, setMap] = useState<MarketMapData | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [selected, setSelected] = useState<Signal | null>(null);

  useEffect(() => {
    Promise.all([api.marketMap(), api.signals()])
      .then(([m, s]) => {
        setMap(m);
        setSignals(s);
        if (s.length > 0) setSelected(s[0]);
      })
      .catch(() => {});
  }, []);

  const activePath = map?.nodes
    .filter((n) => selected && [selected.asset].includes(n.symbol))
    .map((n) => n.id);

  return (
    <div className="flow-layout">
      <div className="flow-map">
        {map && map.nodes.length > 0 ? (
          <MarketMap data={map} activePath={activePath} />
        ) : (
          <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--text-muted)" }}>
            No relationship data yet — run the pipeline to populate the graph
          </div>
        )}
      </div>

      <div className="flow-side">
        <div className="panel-head"><span>Information Flow</span></div>

        <div className="chip-row">
          {signals.map((s) => (
            <button
              key={s.id}
              onClick={() => setSelected(s)}
              className={`chip mono ${selected?.id === s.id ? "active" : ""}`}
            >
              {s.asset}
            </button>
          ))}
        </div>

        {selected ? (
          <>
            <CausalChain signal={selected} />
      {selected.narrative && (
          <div style={{ padding: "0 24px 24px" }}>
            <div className="agent-tag">
              <span className="qdot" />
              Qwen — Narrator
            </div>
            <p className="agent-text">{selected.narrative}</p>
          </div>
        )}
          </>
        ) : (
          <p style={{ padding: 20, fontSize: 13, color: "var(--text-muted)" }}>
            Select a signal to see its causal chain
          </p>
        )}
      </div>
    </div>
  );
}
