// Placeholder for exported GetAgent Playbooks.
// Real data will come from POST /playbook/export + GET /playbook/packages
// once Gate A (real export → validate.py → sandbox run) is complete.
// Until then this page must not display fabricated Sharpe / win-rate / rank numbers.

export type PlaybookPackage = {
  id: string;
  signal_id: number | null;
  name: string;
  leader: string;
  follower: string;
  status: "exported" | "validated" | "sandbox_run" | "published" | "failed";
  exported_at: string | null;
  getagent_run_id: string | null;
  note: string;
};

/** Empty until real packages exist. Do not invent metrics. */
export const PLAYBOOK_PACKAGES: PlaybookPackage[] = [];
