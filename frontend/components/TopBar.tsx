"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { api, Regime, Signal, MarketTick } from "@/lib/api";
import { useShell } from "./ShellContext";

const REGIME_LABEL: Record<Regime["regime"], string> = {
  RISK_ON: "Risk-On",
  RISK_OFF: "Risk-Off",
  NEUTRAL: "Neutral",
};

function SearchBar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [assets, setAssets] = useState<MarketTick[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    Promise.all([api.signals(), api.liveMarket()])
      .then(([s, a]) => {
        setSignals(s);
        setAssets(a);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const q = query.trim().toUpperCase();
  const matchingSignals = q ? signals.filter((s) => s.asset.toUpperCase().includes(q)).slice(0, 5) : [];
  const matchedSymbols = new Set(matchingSignals.map((s) => s.asset));
  const matchingAssets = q
    ? assets.filter((a) => a.symbol.toUpperCase().includes(q) && !matchedSymbols.has(a.symbol)).slice(0, 5)
    : [];
  const hasResults = matchingSignals.length > 0 || matchingAssets.length > 0;

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      <input
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder="Search symbol…"
        className="search-input mono"
      />
      {open && q && (
        <div
          style={{
            position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 20, width: 288,
            background: "var(--panel-solid)", border: "1px solid var(--border)", borderRadius: 12,
            boxShadow: "0 12px 32px -8px rgba(0,0,0,0.5)", overflow: "hidden",
          }}
        >
          {!hasResults ? (
            <div style={{ padding: "14px 14px", fontSize: 12.5, color: "var(--text-muted)" }}>
              No matches for &quot;{q}&quot;
            </div>
          ) : (
            <>
              {matchingSignals.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    router.push(`/simulation?signal=${s.id}`);
                    setOpen(false);
                    setQuery("");
                  }}
                  style={{
                    display: "flex", width: "100%", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 14px", background: "transparent", border: "none", cursor: "pointer",
                    color: "var(--text-primary)", textAlign: "left",
                  }}
                  className="mono"
                >
                  <span style={{ fontSize: 13 }}>{s.asset}</span>
                  <span className={s.direction === "LONG" ? "up" : "down"} style={{ fontSize: 12.5 }}>
                    {s.direction} · {Math.round(s.alpha_score)}
                  </span>
                </button>
              ))}
              {matchingAssets.map((a) => (
                <button
                  key={a.symbol}
                  onClick={() => {
                    router.push("/signals");
                    setOpen(false);
                    setQuery("");
                  }}
                  style={{
                    display: "flex", width: "100%", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 14px", background: "transparent", border: "none", cursor: "pointer",
                    color: "var(--text-primary)", textAlign: "left",
                  }}
                  className="mono"
                >
                  <span style={{ fontSize: 13 }}>{a.symbol}</span>
                  <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>no active signal</span>
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function TopBar() {
  const [regime, setRegime] = useState<Regime | null>(null);
  const { openMobile } = useShell();

  useEffect(() => {
    let mounted = true;
    api.regime().then((r) => mounted && setRegime(r)).catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <header className="topbar">
      <div className="left">
        <button className="hamburger" onClick={openMobile} aria-label="Open menu">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
        </button>
        <span>Cross-Market Intelligence</span>
      </div>
      <div className="right">
        <SearchBar />
        <div className="divider" />
        <div className="regime-row">
          <span className="label">Regime</span>
          <span className={`val mono ${regime?.regime === "RISK_OFF" ? "down" : "up"}`}>
            {regime ? REGIME_LABEL[regime.regime] : "—"}
          </span>
        </div>
        <div className="divider" />
        <div className="gate-row">
          <span className="pulse" />
          <span className="label">Risk Gate active</span>
        </div>
      </div>
    </header>
  );
}
