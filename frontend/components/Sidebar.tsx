"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, MarketTick } from "@/lib/api";
import { useShell } from "./ShellContext";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: "dashboard" },
  { href: "/market-map", label: "Information Flow", icon: "map" },
  { href: "/signals", label: "Signals", icon: "signals" },
  { href: "/oracle", label: "Oracle", icon: "oracle" },
  { href: "/backtest", label: "Backtests", icon: "backtest" },
  { href: "/flight-radar", label: "Flight Radar", icon: "radar" },
  { href: "/playbooks", label: "Playbooks", icon: "playbooks" },
  { href: "/news", label: "News", icon: "news" },
  { href: "/simulation", label: "Simulations", icon: "sim" },
  { href: "/ops", label: "Ops", icon: "ops" },
];

const ICONS: Record<string, JSX.Element> = {
  dashboard: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>
  ),
  map: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><path d="M8.6 7.4L15.4 15.6M15.4 7.4L8.6 15.6"/></svg>
  ),
  signals: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 17l5-6 4 4 9-11"/><path d="M15 4h6v6"/></svg>
  ),
  radar: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z"/></svg>
  ),
  playbooks: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5v-17Z"/><path d="M4 19a2.5 2.5 0 0 1 2.5-2.5H20"/></svg>
  ),
  news: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 11a9 9 0 0 1 9 9"/><path d="M4 4a16 16 0 0 1 16 16"/><circle cx="5" cy="19" r="1.6" fill="currentColor" stroke="none"/></svg>
  ),
  sim: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 2v6.2L4.5 17a2 2 0 0 0 1.8 2.9h11.4a2 2 0 0 0 1.8-2.9L15 8.2V2"/><path d="M8.5 2h7"/><path d="M7 15h10"/></svg>
  ),
  oracle: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
  ),
  backtest: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 15v-4"/><path d="M12 15V8"/><path d="M16 15v-6"/></svg>
  ),
  ops: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>
  ),
};

function fmtPct(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
}

export default function Sidebar() {
  const pathname = usePathname();
  const [ticks, setTicks] = useState<MarketTick[]>([]);
  const { mobileOpen, closeMobile, toggleCollapsed } = useShell();

  useEffect(() => {
    let mounted = true;
    api
      .liveMarket()
      .then((data) => mounted && setTicks(data))
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <aside className={`sidebar${mobileOpen ? " mobile-open" : ""}`}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <Link href="/dashboard" className="brand" style={{ flex: 1, minWidth: 0 }} onClick={closeMobile}>
          <span className="dot" />
          <span className="mono">ORACLE X</span>
        </Link>
        <button className="collapse-btn" style={{ marginRight: 14 }} onClick={toggleCollapsed} title="Collapse menu" aria-label="Collapse menu">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M15 6l-6 6 6 6"/></svg>
        </button>
      </div>

      <nav className="nav">
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={pathname === item.href ? "active" : ""}
            onClick={closeMobile}
            title={item.label}
          >
            {ICONS[item.icon]}
            <span className="nav-label">{item.label}</span>
          </Link>
        ))}
      </nav>

      <div className="watchlist-label">Watchlist</div>
      <div className="watchlist">
        {ticks.length === 0 && (
          <p style={{ padding: "0 10px", fontSize: 12.5, color: "var(--text-muted)" }}>
            No market data yet
          </p>
        )}
        {ticks.map((t) => (
          <div key={t.symbol} className="tick">
            <span className="sym mono">{t.symbol}</span>
            <span className={`chg mono tabular ${t.change_pct >= 0 ? "up" : "down"}`}>
              {fmtPct(t.change_pct)}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
