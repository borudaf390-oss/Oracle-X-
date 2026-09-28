"use client";

import Link from "next/link";
import { PLAYBOOK_PACKAGES, PlaybookPackage } from "@/lib/playbooks-data";

const STATUS_LABEL: Record<PlaybookPackage["status"], string> = {
  exported: "Exported",
  validated: "Validated",
  sandbox_run: "Sandbox run",
  published: "Published",
  failed: "Failed",
};

const STATUS_CLASS: Record<PlaybookPackage["status"], string> = {
  exported: "pending",
  validated: "pending",
  sandbox_run: "pending",
  published: "pass",
  failed: "fail",
};

export default function PlaybooksPage() {
  const packages = PLAYBOOK_PACKAGES;

  return (
    <>
      <div
        className="panel"
        style={{
          padding: "16px 20px",
          marginBottom: 14,
          display: "flex",
          flexWrap: "wrap",
          gap: 10,
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <p style={{ fontSize: 12.5, color: "var(--text-secondary)", maxWidth: 720, margin: 0 }}>
          Locked relationship contracts exported for{" "}
          <span style={{ color: "var(--text-primary)" }}>GetAgent Playbook</span> verification.
          Only signals that passed the deterministic Risk Gate can be exported. Metrics appear
          only after an official sandbox run produces an equity curve — never before.
        </p>
      </div>

      {packages.length === 0 ? (
        <div className="panel" style={{ padding: "48px 24px", textAlign: "center" }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", marginBottom: 10 }}>
            No playbook packages yet
          </div>
          <p style={{ fontSize: 12.5, color: "var(--text-secondary)", maxWidth: 480, margin: "0 auto 18px", lineHeight: 1.6 }}>
            Export a PASS signal with{" "}
            <code className="mono" style={{ fontSize: 11.5 }}>
              python -m app.jobs.export_playbook --signal-id &lt;id&gt;
            </code>
            , run <code className="mono" style={{ fontSize: 11.5 }}>validate.py</code> on the
            generated directory, then wire the result here. Fabricated leaderboard ranks and
            Sharpe numbers have been removed.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <Link
              href="/signals"
              style={{
                background: "linear-gradient(135deg, #0fdc85, #0f6b4d)",
                color: "#04130c",
                fontWeight: 700,
                padding: "10px 18px",
                borderRadius: 10,
                fontSize: 12.5,
                textDecoration: "none",
                boxShadow: "0 0 22px -6px var(--signal-glow)",
              }}
            >
              View PASS signals →
            </Link>
            <Link
              href="/dashboard"
              className="link mono"
              style={{ fontSize: 12.5, padding: "10px 14px" }}
            >
              Back to overview
            </Link>
          </div>
        </div>
      ) : (
        <div className="playbook-layout">
          <div className="playbook-list">
            <div className="panel-head">
              <span>Exported packages</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                {packages.length} package{packages.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="playbook-list-body">
              {packages.map((p) => (
                <div key={p.id} className="playbook-row">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start" }}>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)" }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                        {p.leader} → {p.follower}
                      </div>
                    </div>
                    <span className={`risk-badge ${STATUS_CLASS[p.status]}`}>{STATUS_LABEL[p.status]}</span>
                  </div>
                  {p.note && (
                    <p style={{ fontSize: 11.5, color: "var(--text-secondary)", marginTop: 8, marginBottom: 0 }}>
                      {p.note}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
