"""
Agent 5a — Risk Analyst (advisory layer of Risk Guardian, spec section 12).
Qwen-assisted reasoning about qualitative risk factors. Advisory only —
cannot itself pass or fail a signal. B5: provenance is returned with the opinion.
"""
from sqlalchemy.orm import Session
from app.models import Signal
from app.data.qwen_client import QwenClient


class RiskAnalyst:
    def __init__(self, db: Session, qwen: QwenClient = None):
        self.db = db
        self.qwen = qwen or QwenClient()

    def assess(self, signal: Signal) -> dict:
        """
        Returns {
          "recommendation": "PROCEED"|"CAUTION"|"AVOID",
          "reasoning": str,
          "qwen_provenance": {...},
        }
        Advisory only — logged onto the signal but does not set risk_status.
        """
        context = {
            "alpha_score": float(signal.alpha_score),
            "confidence": float(signal.confidence),
            "direction": signal.direction,
            "reason_json": signal.reason_json,
        }
        opinion, provenance = self.qwen.risk_opinion(context)
        opinion["qwen_provenance"] = provenance
        return opinion
