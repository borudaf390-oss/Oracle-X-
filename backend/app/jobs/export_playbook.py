"""
Export one Oracle X signal as a GetAgent Playbook package.

Usage:
    python -m app.jobs.export_playbook --signal-id 42
    python -m app.jobs.export_playbook            # picks the highest
                                                    # alpha_score PASS signal

Writes to ./playbook/<slug>/ (manifest.yaml, backtest.yaml, src/main.py,
src/strategy.py) — see app/playbook/translator.py's docstring for what's
confirmed-real about that schema vs. reconstructed, and verify against the
actual `npx @bitget-ai/getagent-skill` scaffold before publishing.
"""
import argparse
import sys
from app.db import SessionLocal
from app.models import Signal
from app.playbook.contract import build_locked_relationship_contract
from app.playbook.translator import write_playbook_package


def run(signal_id: int | None = None, output_dir: str = "."):
    db = SessionLocal()
    try:
        if signal_id is None:
            best = (
                db.query(Signal)
                .filter(Signal.risk_status == "PASS")
                .order_by(Signal.alpha_score.desc())
                .first()
            )
            if not best:
                print("no PASS signals found — run the pipeline first, or pass --signal-id explicitly")
                return
            signal_id = best.id

        contract = build_locked_relationship_contract(db, signal_id)
        package_dir = write_playbook_package(contract, output_dir)
        print(f"exported signal {signal_id} ({contract.leader_symbol}->{contract.follower_symbol}) "
              f"to {package_dir}")
        print("REMINDER: verify manifest.yaml/backtest.yaml against the real "
              "`npx @bitget-ai/getagent-skill` scaffold before publishing — "
              "see translator.py's docstring for exactly what is/isn't confirmed.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-id", type=int, default=None)
    parser.add_argument("--output-dir", type=str, default=".")
    args = parser.parse_args()
    run(signal_id=args.signal_id, output_dir=args.output_dir)
