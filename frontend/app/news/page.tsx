"use client";

import { useEffect, useState } from "react";
import { api, NewsItem } from "@/lib/api";

const SENT_CLASS: Record<string, string> = {
  bullish: "sent-bullish",
  bearish: "sent-bearish",
  neutral: "sent-neutral",
};

function timeAgo(iso: string) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function NewsPage() {
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  function load() {
    api.news().then(setNews).catch(() => {}).finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  async function runAgentNow() {
    setTriggering(true);
    setTriggerMsg(null);
    try {
      await api.triggerJob("ingest_events");
      setTriggerMsg("Sentinel is fetching headlines now — refresh in ~30s.");
    } catch {
      setTriggerMsg("Trigger failed — check backend logs.");
    } finally {
      setTriggering(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 560, lineHeight: 1.5 }}>
          Raw headlines picked up by Sentinel, structured by <b style={{ color: "var(--text-primary)" }}>Qwen — Interpreter</b> (sentiment,
          magnitude, affected assets) — this is the event feed that triggers the signal pipeline.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {triggerMsg && <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{triggerMsg}</span>}
          <button onClick={runAgentNow} disabled={triggering} className="exec-btn mono" style={{ borderColor: "var(--border-bright)", color: "var(--signal)", opacity: triggering ? 0.5 : 1 }}>
            {triggering ? "Triggering…" : "Run Sentinel now"}
          </button>
          <button onClick={load} className="exec-btn mono">Refresh</button>
        </div>
      </div>

      {loading ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading…</p>
      ) : news.length === 0 ? (
        <div className="panel" style={{ padding: 24 }}>
          <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            No news ingested yet. Sentinel runs automatically every 6 hours (rate-limited by the NewsAPI
            free tier), or tap &quot;Run Sentinel now&quot; to fetch immediately.
          </p>
        </div>
      ) : (
        <div className="panel">
          {news.map((n) => (
            <div key={n.id} className="news-item">
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {n.asset && <span className="mono" style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 500 }}>{n.asset}</span>}
                  <span className="etype">{n.event_type.replace("_", " ")}</span>
                  {!n.interpreted && <span style={{ fontSize: 11, color: "var(--text-muted)" }}>· awaiting interpretation</span>}
                </div>
                <p className="headline">{n.headline}</p>
                <div className="meta">{n.source} · {timeAgo(n.timestamp)}</div>
              </div>
              {n.sentiment && (
                <span className={`sentiment mono ${SENT_CLASS[n.sentiment] ?? ""}`}>{n.sentiment}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
