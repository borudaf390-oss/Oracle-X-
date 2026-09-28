"""
Qwen client — used by Interpreter (structured event extraction),
Narrator (causal-chain explanations), and Risk Analyst (advisory opinion).

OpenAI-compatible endpoint via DashScope / hackathon-provided base URL.

B5 — every call records provenance: model, prompt_version, input/output
hashes, latency_ms, validation_ok. Callers attach this to signal.reason_json
or event metadata so judges can audit which model/prompt produced each claim.
"""
import hashlib
import json
import re
import time
import requests
from app import config

# Bump when system prompts or validation rules change in a material way.
# Stored on every provenance record so a later audit can map a signal back
# to the exact prompt text that produced it.
PROMPT_VERSION = "2026-09-28.v1"

_EVENT_SENTIMENTS = {"bullish", "bearish", "neutral"}
_EVENT_TYPES = {"earnings", "product", "macro", "crypto_news", "sec_filing"}


class QwenClientError(Exception):
    """Raised when Qwen's response can't be parsed/validated after retries."""


def _strip_code_fences(raw: str) -> str:
    """Qwen sometimes wraps JSON in ```json ... ``` despite instructions not to."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    return match.group(1) if match else raw


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _empty_provenance(purpose: str, system: str, user: str) -> dict:
    return {
        "purpose": purpose,
        "model": config.QWEN_MODEL,
        "prompt_version": PROMPT_VERSION,
        "input_hash": _sha256(system + "\n" + user),
        "output_hash": None,
        "latency_ms": None,
        "validation_ok": False,
        "attempts": 0,
        "error": None,
    }


class QwenClient:
    def __init__(self):
        self.base_url = config.QWEN_BASE_URL
        self.api_key = config.QWEN_API_KEY
        self.model = config.QWEN_MODEL

    def _chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        json_mode: bool = False,
        max_retries: int = 2,
        purpose: str = "generic",
    ) -> tuple[str, dict]:
        """
        Returns (content, provenance). Provenance is always populated so
        callers can log failed attempts the same way they log successes.
        """
        provenance = _empty_provenance(purpose, system, user)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_exc = None
        t0 = time.monotonic()
        for attempt in range(max_retries + 1):
            provenance["attempts"] = attempt + 1
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                provenance["latency_ms"] = int((time.monotonic() - t0) * 1000)
                provenance["output_hash"] = _sha256(content)
                provenance["validation_ok"] = True
                return content, provenance
            except (requests.RequestException, KeyError, IndexError, TypeError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** attempt))

        provenance["latency_ms"] = int((time.monotonic() - t0) * 1000)
        provenance["error"] = str(last_exc)
        provenance["validation_ok"] = False
        raise QwenClientError(f"Qwen chat request failed after retries: {last_exc}")

    def extract_event(self, raw_headline: str, raw_source: str = "") -> dict:
        """
        Interpreter agent: raw text -> structured event JSON.
        Never raises on a malformed model response — falls back to a
        clearly-neutral, clearly-flagged result with provenance attached.
        """
        system = (
            "You are a financial event extraction engine. Given a raw news "
            "headline/body, output ONLY a JSON object with keys: "
            "asset (ticker), event_type (earnings|product|macro|crypto_news|sec_filing), "
            "sentiment (bullish|bearish|neutral), magnitude (0.0-1.0), "
            "horizon_hours (int), affected_assets (list of tickers plausibly "
            "impacted downstream). No prose, no markdown, JSON only."
        )
        user = f"HEADLINE: {raw_headline}\nSOURCE: {raw_source}"
        fallback = {
            "asset": None,
            "event_type": "macro",
            "sentiment": "neutral",
            "magnitude": 0.0,
            "horizon_hours": 0,
            "affected_assets": [],
            "extraction_failed": True,
            "qwen_provenance": _empty_provenance("interpreter.extract_event", system, user),
        }
        try:
            raw, provenance = self._chat(
                system, user, json_mode=True, purpose="interpreter.extract_event"
            )
        except QwenClientError as exc:
            print(f"  [qwen extract_event] request failed, using neutral fallback: {exc}")
            fallback["qwen_provenance"]["error"] = str(exc)
            return fallback

        try:
            parsed = json.loads(_strip_code_fences(raw))
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"  [qwen extract_event] unparsable JSON, using neutral fallback: {exc}")
            provenance["validation_ok"] = False
            provenance["error"] = f"json_parse: {exc}"
            fallback["qwen_provenance"] = provenance
            return fallback

        result = self._validate_event(parsed, fallback)
        # If validation forced the full fallback shape, keep extraction_failed
        if result.get("extraction_failed"):
            provenance["validation_ok"] = False
            provenance["error"] = provenance.get("error") or "schema_validation_failed"
        result["qwen_provenance"] = provenance
        return result

    @staticmethod
    def _validate_event(parsed: dict, fallback: dict) -> dict:
        """Coerces/validates each field independently rather than all-or-nothing."""
        if not isinstance(parsed, dict):
            return fallback

        sentiment = parsed.get("sentiment")
        if sentiment not in _EVENT_SENTIMENTS:
            sentiment = "neutral"

        event_type = parsed.get("event_type")
        if event_type not in _EVENT_TYPES:
            event_type = "macro"

        try:
            magnitude = max(0.0, min(1.0, float(parsed.get("magnitude", 0.0))))
        except (TypeError, ValueError):
            magnitude = 0.0

        try:
            horizon_hours = int(parsed.get("horizon_hours", 0))
        except (TypeError, ValueError):
            horizon_hours = 0

        affected = parsed.get("affected_assets", [])
        affected_assets = (
            [a for a in affected if isinstance(a, str)] if isinstance(affected, list) else []
        )

        return {
            "asset": parsed.get("asset") if isinstance(parsed.get("asset"), str) else None,
            "event_type": event_type,
            "sentiment": sentiment,
            "magnitude": magnitude,
            "horizon_hours": horizon_hours,
            "affected_assets": affected_assets,
            "extraction_failed": False,
        }

    def explain_causal_chain(self, signal_context: dict) -> tuple[str, dict]:
        """Narrator agent. Returns (narrative_text, provenance)."""
        system = (
            "You are Oracle X's Narrator. Given structured signal data "
            "(triggering event, correlation chain, displacement, historical "
            "analogues, alpha score), write a concise, confident causal-chain "
            "explanation a trader would read in under 15 seconds. No hedging "
            "filler, no disclaimers, just the reasoning chain and the evidence."
        )
        user = json.dumps(signal_context)
        return self._chat(system, user, temperature=0.4, purpose="narrator.explain_causal_chain")

    def explain_what_changed(self, before: dict, after: dict) -> tuple[str, dict]:
        """WHY? / 'What Changed?' button."""
        system = (
            "You are Oracle X. Given 'before event' and 'after event' market "
            "state (correlation, displacement, volume, sentiment, regime), "
            "explain in 2-3 sentences what structurally changed and why it "
            "matters for this signal."
        )
        user = json.dumps({"before": before, "after": after})
        return self._chat(system, user, temperature=0.3, purpose="narrator.what_changed")

    def risk_opinion(self, context: dict) -> tuple[dict, dict]:
        """
        Risk Analyst advisory call. Returns (opinion_dict, provenance).
        On parse failure returns a safe CAUTION opinion with validation_ok=False.
        """
        system = (
            "You are Oracle X's Risk Analyst. You give a qualitative second "
            "opinion on a trading signal already scored by the quant engine. "
            "Respond ONLY with JSON: {\"recommendation\": \"PROCEED\"|\"CAUTION\"|"
            "\"AVOID\", \"reasoning\": \"<one or two sentences>\"}. You are advisory "
            "only — the deterministic Risk Gate makes the actual pass/block "
            "decision, so focus on qualitative concerns (data staleness, "
            "unusual event types, thin historical basis) rather than restating "
            "numeric thresholds."
        )
        user = json.dumps(context)
        try:
            raw, provenance = self._chat(
                system, user, json_mode=True, purpose="risk_analyst.assess"
            )
        except QwenClientError as exc:
            return (
                {"recommendation": "CAUTION", "reasoning": f"Risk Analyst unavailable: {exc}"},
                {**_empty_provenance("risk_analyst.assess", system, user), "error": str(exc)},
            )
        try:
            parsed = json.loads(_strip_code_fences(raw))
            if not isinstance(parsed, dict):
                raise ValueError("not a dict")
            rec = parsed.get("recommendation")
            if rec not in {"PROCEED", "CAUTION", "AVOID"}:
                rec = "CAUTION"
            reasoning = parsed.get("reasoning") if isinstance(parsed.get("reasoning"), str) else ""
            return {"recommendation": rec, "reasoning": reasoning}, provenance
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            provenance["validation_ok"] = False
            provenance["error"] = f"json_parse: {exc}"
            return (
                {"recommendation": "CAUTION", "reasoning": "Risk Analyst response unparsable."},
                provenance,
            )
