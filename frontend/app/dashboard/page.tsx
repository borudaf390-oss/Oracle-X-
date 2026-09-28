"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Signal, MarketMapData } from "@/lib/api";
import OpportunityCard from "@/components/OpportunityCard";
import MarketMap from "@/components/MarketMap";
import GlobeHero from "@/components/GlobeHero";

export default function DashboardPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [map, setMap] = useState<MarketMapData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.signals(), api.marketMap()])
      .then(([s, m]) => {
        setSignals(s);
        setMap(m);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const active = signals.filter((s) => s.status === "OPEN" || s.status === "SIMULATED");
  const strongAlpha = active.filter((s) => s.alpha_score >= 75);
  const blocked = signals.filter((s) => s.risk_status === "BLOCK");
  const top = [...active].sort((a, b) => b.alpha_score - a.alpha_score)[0];

  return (
    <>
      <GlobeHero signals={signals} />

      <div className="stats">
        <div className="stat">
          <div className="l">Active signals</div>
          <div className="v mono tabular">{active.length}</div>
        </div>
        <div className="stat accent-glow">
          <div className="l">Strong alpha</div>
          <div className="v mono tabular accent">{strongAlpha.length}</div>
        </div>
        <div className="stat">
          <div className="l">Avg alpha score</div>
          <div className="v mono tabular">
            {active.length ? Math.round(active.reduce((sum, s) => sum + s.alpha_score, 0) / active.length) : "—"}
          </div>
        </div>
        <div className="stat">
          <div className="l">Blocked by Risk Gate</div>
          <div className="v mono tabular">{blocked.length}</div>
        </div>
      </div>

      <div className="panels">
        <div className="panel">
          <div className="panel-head">
            <span>Cross-Market Relationship Map</span>
            <Link href="/market-map" className="link mono">Open full view →</Link>
          </div>
          <div className="panel-body">
            {map && map.nodes.length > 0 ? (
              <MarketMap data={map} />
            ) : (
              <EmptyState loading={loading} label="No market data ingested yet" />
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span>Top Opportunity</span>
            <Link href="/signals" className="link mono">All signals →</Link>
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
            {top ? (
              <>
                <div style={{ margin: 16 }}>
                  <OpportunityCard signal={top} />
                </div>
                <div className="news-row">
                  <span className="news-dot" />
                  <span className="news-text">
                    Check the <b>News</b> feed for the latest headlines feeding the pipeline —{" "}
                    <Link href="/news" className="mono link" style={{ textDecoration: "underline" }}>view</Link>
                  </span>
                </div>
              </>
            ) : (
              <EmptyState loading={loading} label="No signals yet" />
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function EmptyState({ loading, label }: { loading: boolean; label: string }) {
  return (
    <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center" }}>
      <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{loading ? "Loading…" : label}</span>
    </div>
  );
}
