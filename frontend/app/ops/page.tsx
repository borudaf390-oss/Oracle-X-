"use client";

import { useCallback, useEffect, useState } from "react";
import { api, OpsHealth } from "@/lib/api";

function ageLabel(seconds: number | null | undefined) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function freshnessTone(seconds: number | null | undefined, warnS: number, badS: number) {
  if (seconds == null) return "fail";
  if (seconds > badS) return "fail";
  if (seconds > warnS) return "pending";
  return "pass";
}

export default function OpsPage() {
  const [health, setHealth] = useState<OpsHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .opsHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  async function trigger(name: string) {
    setTriggering(name);
    setMsg(null);
    try {
      await api.triggerJob(name);
      setMsg(`Triggered ${name} — status refreshes shortly.`);
      setTimeout(load, 2000);
    } catch {
      setMsg(`Failed to trigger ${name}`);
    } finally {
      setTriggering(null);
    }
  }

  const f = health?.freshness;
  const jobs = health?.jobs ?? [];
  const registered = health?.scheduler?.registered_jobs ?? [];

  return (
    <>
      <div className="toolbar">
        <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 640, lineHeight: 1.5 }}>
          Scheduler leader, job runs, and data freshness. Jobs are guarded by a Postgres advisory
          lock so only one API replica runs the background schedule.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {msg && <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{msg}</span>}
          <button onClick={load} className="exec-btn mono">
            Refresh
          </button>
        </div>
      </div>

      {loading && !health ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading…</p>
      ) : !health ? (
        <div className="panel" style={{ padding: 24 }}>
          <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            Could not reach <code className="mono">/jobs/health</code>. Is the API up?
          </p>
        </div>
      ) : (
        <>
          <div className="stats" style={{ marginBottom: 14 }}>
            <div className="stat">
              <div className="l">Scheduler lock</div>
              <div className="v mono tabular">
                {health.scheduler.lock_held == null
                  ? "unknown"
                  : health.scheduler.lock_held
                    ? "held"
                    : "free"}
              </div>
            </div>
            <div className="stat">
              <div className="l">Open signals</div>
              <div className="v mono tabular">{health.counts.open_signals}</div>
            </div>
            <div className="stat accent-glow">
              <div className="l">PASS</div>
              <div className="v mono tabular accent">{health.counts.pass_signals}</div>
            </div>
            <div className="stat">
              <div className="l">BLOCK</div>
              <div className="v mono tabular">{health.counts.block_signals}</div>
            </div>
          </div>

          <div className="panels" style={{ marginBottom: 14 }}>
            <div className="panel">
              <div className="panel-head">
                <span>Data freshness</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                  {health.counts.assets} assets
                </span>
              </div>
              <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <FreshRow
                  label="Market candles"
                  age={f?.latest_market_candle_age_s}
                  at={f?.latest_market_candle_at}
                  warn={3600 * 3}
                  bad={3600 * 12}
                />
                <FreshRow
                  label="Oracle ticks"
                  age={f?.latest_oracle_tick_age_s}
                  at={f?.latest_oracle_tick_at}
                  warn={600}
                  bad={1800}
                />
                <FreshRow
                  label="Events"
                  age={f?.latest_event_age_s}
                  at={f?.latest_event_at}
                  warn={3600 * 8}
                  bad={3600 * 24}
                />
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <span>Scheduler</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                  advisory {health.scheduler.advisory_lock_enabled ? "on" : "off"}
                </span>
              </div>
              <div className="panel-body">
                <p style={{ fontSize: 12.5, color: "var(--text-secondary)", margin: "0 0 10px" }}>
                  Registered jobs on this process:
                </p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {registered.length === 0 ? (
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      None registered (this process may not be the leader)
                    </span>
                  ) : (
                    registered.map((name) => (
                      <button
                        key={name}
                        className="exec-btn mono"
                        style={{ fontSize: 11, padding: "6px 10px" }}
                        disabled={triggering === name}
                        onClick={() => trigger(name)}
                      >
                        {triggering === name ? "…" : name}
                      </button>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <span>Job status</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                server {health.server_time.slice(0, 19).replace("T", " ")} UTC
              </span>
            </div>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }} className="mono">
                <thead>
                  <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
                    <th style={{ padding: "8px 12px" }}>Job</th>
                    <th style={{ padding: "8px 12px" }}>Runs</th>
                    <th style={{ padding: "8px 12px" }}>Last run</th>
                    <th style={{ padding: "8px 12px" }}>Last success</th>
                    <th style={{ padding: "8px 12px" }}>Status</th>
                    <th style={{ padding: "8px 12px" }}>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={{ padding: 16, color: "var(--text-muted)" }}>
                        No job rows yet — scheduler has not recorded a run.
                      </td>
                    </tr>
                  ) : (
                    jobs.map((j) => (
                      <tr key={j.job_name} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={{ padding: "8px 12px", color: "var(--text-primary)", fontWeight: 600 }}>
                          {j.job_name}
                        </td>
                        <td style={{ padding: "8px 12px" }}>{j.run_count}</td>
                        <td style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>
                          {j.last_run_at ? j.last_run_at.slice(0, 19).replace("T", " ") : "—"}
                        </td>
                        <td style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>
                          {j.last_success_at ? j.last_success_at.slice(0, 19).replace("T", " ") : "—"}
                        </td>
                        <td style={{ padding: "8px 12px" }}>
                          <span className={`risk-badge ${j.healthy ? "pass" : "fail"}`}>
                            {j.healthy ? "OK" : "ERR"}
                          </span>
                        </td>
                        <td
                          style={{
                            padding: "8px 12px",
                            color: "var(--short)",
                            maxWidth: 280,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={j.last_error ?? undefined}
                        >
                          {j.last_error ?? ""}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function FreshRow({
  label,
  age,
  at,
  warn,
  bad,
}: {
  label: string;
  age: number | null | undefined;
  at: string | null | undefined;
  warn: number;
  bad: number;
}) {
  const tone = freshnessTone(age, warn, bad);
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
      <div>
        <div style={{ fontSize: 12.5, color: "var(--text-primary)", fontWeight: 600 }}>{label}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }} className="mono">
          {at ? at.slice(0, 19).replace("T", " ") : "never"}
        </div>
      </div>
      <span className={`risk-badge ${tone}`}>{ageLabel(age)}</span>
    </div>
  );
}
