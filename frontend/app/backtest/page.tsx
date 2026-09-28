"use client";

import { useEffect, useState } from "react";
import { api, BacktestRun, BacktestRunDetail, PerformanceSummary } from "@/lib/api";

function fmtPct(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

function PerfGrid({ title, p }: { title: string; p: PerformanceSummary }) {
  return (
    <div className="panel" style={{ padding: 16 }}>
      <div className="panel-head" style={{ marginBottom: 10 }}>
        <span>{title}</span>
        <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
          {p.trades} trades
        </span>
      </div>
      <div className="grid2 mono">
        <div>
          <div className="l">WIN RATE</div>
          <div className="v">{p.win_rate != null ? `${Number(p.win_rate).toFixed(1)}%` : "—"}</div>
        </div>
        <div>
          <div className="l">EXPECTANCY</div>
          <div className={`v ${p.expectancy_pct != null && p.expectancy_pct >= 0 ? "up" : "down"}`}>
            {fmtPct(p.expectancy_pct)}
          </div>
        </div>
        <div>
          <div className="l">PROFIT FACTOR</div>
          <div className="v">{fmtNum(p.profit_factor)}</div>
        </div>
        <div>
          <div className="l">SHARPE</div>
          <div className="v">{fmtNum(p.sharpe)}</div>
        </div>
        <div>
          <div className="l">SORTINO</div>
          <div className="v">{fmtNum(p.sortino)}</div>
        </div>
        <div>
          <div className="l">MAX DD</div>
          <div className="v down">{fmtPct(p.max_drawdown_pct != null ? -Math.abs(p.max_drawdown_pct) : null)}</div>
        </div>
      </div>
    </div>
  );
}

export default function BacktestPage() {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<BacktestRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    api
      .backtestRuns()
      .then((r) => {
        setRuns(r);
        if (r.length) setSelectedId(r[0].run_id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setDetailLoading(true);
    api
      .backtestRunDetail(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selectedId]);

  return (
    <>
      <div className="toolbar">
        <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 640, lineHeight: 1.5 }}>
          Walk-forward backtests of locked leader→follower relationships. Coverage badge reflects
          actual history depth vs the requested window — <b style={{ color: "var(--text-primary)" }}>INSUFFICIENT</b>{" "}
          means the run should not be treated as a validation claim.
        </p>
      </div>

      {loading ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading…</p>
      ) : runs.length === 0 ? (
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>No backtest runs yet</div>
          <p style={{ fontSize: 12.5, color: "var(--text-secondary)", maxWidth: 420, margin: "0 auto" }}>
            Run <code className="mono" style={{ fontSize: 11.5 }}>python -m app.jobs.run_backtest</code> against
            a DB with market history. Results appear here with in-sample vs out-of-sample splits.
          </p>
        </div>
      ) : (
        <div className="playbook-layout">
          <div className="playbook-list">
            <div className="panel-head">
              <span>Runs</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                {runs.length} run{runs.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="playbook-list-body">
              {runs.map((r) => (
                <button
                  key={r.run_id}
                  className={`playbook-row ${r.run_id === selectedId ? "active" : ""}`}
                  onClick={() => setSelectedId(r.run_id)}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>
                        {r.leader ?? "?"} → {r.follower ?? "?"}
                      </div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }} className="mono">
                        {r.run_id.slice(0, 12)}…
                      </div>
                    </div>
                    <span className={`risk-badge ${r.coverage_status === "VALID" ? "pass" : "fail"}`}>
                      {r.coverage_status}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 9, fontSize: 11 }} className="mono">
                    <span style={{ color: "var(--text-secondary)" }}>
                      {r.event_count} events · hit {r.hit_rate != null ? `${r.hit_rate}%` : "—"}
                    </span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {Math.min(r.leader_coverage_days, r.follower_coverage_days).toFixed(0)}d / {r.requested_window_days}d
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div className="playbook-detail">
            {detailLoading || !detail ? (
              <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
                {detailLoading ? "Loading detail…" : "Select a run"}
              </p>
            ) : (
              <>
                <div style={{ display: "grid", gap: 12, marginBottom: 16 }}>
                  <PerfGrid title="Overall" p={detail.performance.overall} />
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <PerfGrid title="In-sample" p={detail.performance.in_sample} />
                    <PerfGrid title="Out-of-sample" p={detail.performance.out_of_sample} />
                  </div>
                </div>

                <div className="panel-head" style={{ marginBottom: 8 }}>
                  <span>Events</span>
                  <span className="mono" style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                    {detail.events.length}
                  </span>
                </div>
                <div style={{ overflowX: "auto", maxHeight: 360 }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }} className="mono">
                    <thead>
                      <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
                        <th style={{ padding: "6px 8px" }}>Time</th>
                        <th style={{ padding: "6px 8px" }}>Leader</th>
                        <th style={{ padding: "6px 8px" }}>Predicted</th>
                        <th style={{ padding: "6px 8px" }}>Actual</th>
                        <th style={{ padding: "6px 8px" }}>Hit</th>
                        <th style={{ padding: "6px 8px" }}>Split</th>
                        <th style={{ padding: "6px 8px" }}>R²</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.events.map((e, i) => (
                        <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                          <td style={{ padding: "6px 8px", color: "var(--text-secondary)" }}>
                            {e.event_timestamp.slice(0, 16).replace("T", " ")}
                          </td>
                          <td style={{ padding: "6px 8px" }} className={e.leader_move_pct >= 0 ? "up" : "down"}>
                            {fmtPct(e.leader_move_pct * 100)}
                          </td>
                          <td style={{ padding: "6px 8px" }}>{fmtPct(e.predicted_move_pct * 100)}</td>
                          <td style={{ padding: "6px 8px" }} className={e.actual_move_pct >= 0 ? "up" : "down"}>
                            {fmtPct(e.actual_move_pct * 100)}
                          </td>
                          <td style={{ padding: "6px 8px" }}>
                            <span className={`risk-badge ${e.direction_correct ? "pass" : "fail"}`}>
                              {e.direction_correct ? "Y" : "N"}
                            </span>
                          </td>
                          <td style={{ padding: "6px 8px", color: "var(--text-muted)" }}>
                            {e.in_sample ? "IS" : "OOS"}
                          </td>
                          <td style={{ padding: "6px 8px" }}>{fmtNum(e.r_squared_at_time, 3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
