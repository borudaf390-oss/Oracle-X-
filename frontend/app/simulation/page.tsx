// Deliberately NOT a Client Component. Per Next.js's own docs:
// "setting `dynamic` in a Client Component ('use client') page.tsx has no
// effect." This page had `dynamic = 'force-dynamic'` fail silently while
// it carried `"use client"`. Keeping this file a Server Component makes
// `force-dynamic` actually apply, so the route is never statically
// prerendered at all — sidesteps the useSearchParams/Suspense build-time
// detection entirely instead of depending on it working correctly.
export const dynamic = "force-dynamic";

import { Suspense } from "react";
import SimulationView from "@/components/SimulationView";

export default function SimulationPage() {
  return (
    <Suspense fallback={<div style={{ padding: 24, fontSize: 13, color: "var(--text-muted)" }}>Loading…</div>}>
      <SimulationView />
    </Suspense>
  );
}
