"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, Signal, SimulationResult } from "@/lib/api";

function fmt(v: number) {
  return v.toFixed(v < 10 ? 4 : 2);
}

export default function SimulationView() {
  const params = useSearchParams();
  const signalId = params.get("signal");

  const [signal, setSignal] = useState<Signal | null>(null);
  const [sim, setSim] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actualReturn, setActualReturn] = useState("");
  const [outcomeResult, setOutcomeResult] = useState<{ prediction_error_pct: number } | null>(null);

  useEffect(() => {
    if (!signalId) return;
    api.signal(Number(signalId)).then(setSignal).catch(() => {});
  }, [signalId]);

  async function runSimulation() {
    if (!signal) return;
    setError(null);
    try {
      const result = await api.simulate(signal.id);
      setSim(result);
    } catch (e) {
      setError("Simulation failed — signal must have risk_status=PASS.");
    }
  }

  async function closeOutcome() {
    if (!signal || actualReturn === "") return;
    const result = await api.closeOutcome(signal.id, {
      actual_return_pct: parseFloat(actualReturn) / 100,
      result_summary: "Manually closed from simulation view",
    });
    setOutcomeResult(result);
  }

  if (!signalId) {
    return (
      <div style={{ display: "flex", height: "100%", alignItems: "center", justifyContent: "center", fontSize: 13, color: "var(--text-muted)" }}>
        Select a signal from the Signals page to simulate.
      </div>
    );
  }

  if (!signal) {
    return <p style={{ fontSize: 13, color: "var(--text-muted)" }}>Loading signal…</p>;
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 20 }}>
        <span className="mono" style={{ fontSize: 28, fontWeight: 600 }}>{signal.asset}</span>
        <span className={`mono ${signal.direction === "LONG" ? "up" : "down"}`} style={{ fontSize: 16, fontWeight: 600 }}>
          {signal.direction}
        </span>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>Alpha {Math.round(signal.alpha_score)}</span>
      </div>

      {!sim ? (
        <div className="panel" style={{ padding: 24 }}>
          <p style={{ fontSize: 13.5, color: "var(--text-secondary)", marginBottom: 16, lineHeight: 1.6 }}>
            Run the Simulation Engine against current market data — entry, stop, target, and R:R are
            computed from this signal&apos;s expected move and Risk Gate&apos;s stop-distance parameters.
          </p>
          <button onClick={runSimulation} className="sim-btn mono">Simulate trade</button>
          {error && <p style={{ marginTop: 12, fontSize: 13, color: "var(--short)" }}>{error}</p>}
        </div>
      ) : (
        <>
          <div className="sim-stats">
            <div className="sim-stat"><div className="l">Entry</div><div className="v mono tabular">{fmt(sim.entry)}</div></div>
            <div className="sim-stat"><div className="l">Stop</div><div className="v mono tabular down">{fmt(sim.stop)}</div></div>
            <div className="sim-stat"><div className="l">Target</div><div className="v mono tabular up">{fmt(sim.target)}</div></div>
          </div>
          <div className="sim-stats">
            <div className="sim-stat"><div className="l">Risk</div><div className="v mono tabular">{fmt(sim.risk_amount)}</div></div>
            <div className="sim-stat"><div className="l">Reward</div><div className="v mono tabular">{fmt(sim.reward_amount)}</div></div>
            <div className="sim-stat"><div className="l">R:R</div><div className="v mono tabular accent">1:{sim.risk_reward.toFixed(1)}</div></div>
          </div>

          <div className="autopsy-box">
            <h3>Trade Autopsy</h3>
            <p>Record the actual outcome to close the loop — this feeds the factor-weight self-improvement update.</p>
            <div className="autopsy-row">
              <input
                type="number"
                step="0.01"
                placeholder="Actual return %"
                value={actualReturn}
                onChange={(e) => setActualReturn(e.target.value)}
                className="autopsy-input mono"
              />
              <button onClick={closeOutcome} className="autopsy-btn mono">Close & record outcome</button>
            </div>
            {outcomeResult && (
              <p style={{ marginTop: 16, fontSize: 13, color: "var(--text-secondary)" }} className="mono">
                Prediction error: {(outcomeResult.prediction_error_pct * 100).toFixed(2)}%
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
