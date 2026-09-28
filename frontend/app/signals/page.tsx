"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Signal } from "@/lib/api";
import OpportunityCard from "@/components/OpportunityCard";

const FILTERS = ["ALL", "PASS", "BLOCK", "PENDING"] as const;

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("ALL");
  const router = useRouter();

  useEffect(() => {
    api.signals().then(setSignals).catch(() => {});
  }, []);

  const filtered = filter === "ALL" ? signals : signals.filter((s) => s.risk_status === filter);

  async function simulate(id: number) {
    router.push(`/simulation?signal=${id}`);
  }

  return (
    <>
      <div className="toolbar">
        <div className="filter-group">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`filter-chip mono ${filter === f ? "active" : ""}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>No signals match this filter.</p>
      ) : (
        <div className="signals-grid">
          {filtered.map((s) => (
            <OpportunityCard key={s.id} signal={s} onSimulate={() => simulate(s.id)} />
          ))}
        </div>
      )}
    </>
  );
}
