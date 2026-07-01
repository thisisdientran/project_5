import hashlib
import time
import uuid
from functools import wraps

from flask import Flask, jsonify, request

from detector import analyze_text
from storage import (
    add_appeal,
    all_audit_entries,
    append_audit_entry,
    create_content_record,
    get_content_record,
    recent_audit_entries,
)

SUBMIT_LIMIT = "10 per minute;100 per day"

app = Flask(__name__)


def make_fallback_limiter():
    buckets = {}

    def seconds_for(unit):
        return {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]

    def parse_rule(rule):
        amount_text, _, rest = rule.partition(" per ")
        amount = int(amount_text.strip())
        unit = rest.strip().split()[0]
        return amount, seconds_for(unit)

    rules = [parse_rule(item.strip()) for item in SUBMIT_LIMIT.split(";")]

    class FallbackLimiter:
        def limit(self, _rule_text):
            def decorator(func):
                @wraps(func)
                def wrapper(*args, **kwargs):
                    now = time.time()
                    key = request.remote_addr or "local"
                    client_bucket = buckets.setdefault(key, [])
                    buckets[key] = [
                        timestamp
                        for timestamp in client_bucket
                        if now - timestamp < 86400
                    ]

                    for allowed, window_seconds in rules:
                        recent = [
                            timestamp
                            for timestamp in buckets[key]
                            if now - timestamp < window_seconds
                        ]
                        if len(recent) >= allowed:
                            return (
                                jsonify(
                                    {
                                        "error": "rate_limit_exceeded",
                                        "message": f"Limit exceeded: {SUBMIT_LIMIT}",
                                    }
                                ),
                                429,
                            )

                    buckets[key].append(now)
                    return func(*args, **kwargs)

                return wrapper

            return decorator

    return FallbackLimiter()


try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],
        storage_uri="memory://",
    )
    RATE_LIMIT_BACKEND = "Flask-Limiter memory://"
except ImportError:  # pragma: no cover - used only when dependency is absent
    limiter = make_fallback_limiter()
    RATE_LIMIT_BACKEND = "local fallback limiter"


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "provenance-guard",
            "rate_limit_backend": RATE_LIMIT_BACKEND,
        }
    )


@app.post("/submit")
@limiter.limit(SUBMIT_LIMIT)
def submit():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    creator_id = str(payload.get("creator_id", "")).strip()

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not creator_id:
        return jsonify({"error": "creator_id is required"}), 400

    content_id = str(uuid.uuid4())
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    analysis = analyze_text(text)
    create_content_record(content_id, creator_id, text, text_hash, analysis)

    signal_scores = {
        signal["name"]: signal["score"] for signal in analysis["signals"]
    }
    audit_entry = append_audit_entry(
        {
            "event_type": "classification",
            "content_id": content_id,
            "creator_id": creator_id,
            "text_hash": text_hash,
            "attribution": analysis["attribution"],
            "confidence": analysis["confidence"],
            "ai_likelihood": analysis["ai_likelihood"],
            "signal_scores": signal_scores,
            "signal_details": {
                signal["name"]: signal.get("details", {})
                for signal in analysis["signals"]
            },
            "signal_sources": {
                signal["name"]: signal.get("source", "local")
                for signal in analysis["signals"]
            },
            "status": "classified",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "attribution": analysis["attribution"],
            "confidence": analysis["confidence"],
            "ai_likelihood": analysis["ai_likelihood"],
            "label": analysis["label"],
            "signals": analysis["signals"],
            "audit_timestamp": audit_entry["timestamp"],
            "status": "classified",
        }
    )


@app.post("/appeal")
def appeal():
    payload = request.get_json(silent=True) or {}
    content_id = str(payload.get("content_id", "")).strip()
    creator_reasoning = str(payload.get("creator_reasoning", "")).strip()

    if not content_id:
        return jsonify({"error": "content_id is required"}), 400
    if not creator_reasoning:
        return jsonify({"error": "creator_reasoning is required"}), 400

    original = get_content_record(content_id)
    if not original:
        return jsonify({"error": "content_id not found"}), 404

    updated = add_appeal(content_id, creator_reasoning)
    appeal_entry = append_audit_entry(
        {
            "event_type": "appeal",
            "content_id": content_id,
            "creator_id": updated["creator_id"],
            "appeal_reasoning": creator_reasoning,
            "original_decision": original["decision"],
            "status": "under_review",
        }
    )

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Appeal received and queued for human review.",
            "appeal_timestamp": appeal_entry["timestamp"],
        }
    )


@app.get("/log")
def log():
    limit = request.args.get("limit", default=10, type=int)
    limit = max(1, min(limit, 100))
    return jsonify({"entries": recent_audit_entries(limit)})


@app.get("/analytics")
def analytics():
    entries = all_audit_entries()
    classifications = [
        entry for entry in entries if entry.get("event_type") == "classification"
    ]
    appeals = [entry for entry in entries if entry.get("event_type") == "appeal"]
    attribution_counts = {}

    for entry in classifications:
        attribution = entry.get("attribution", "unknown")
        attribution_counts[attribution] = attribution_counts.get(attribution, 0) + 1

    average_ai_likelihood = None
    if classifications:
        average_ai_likelihood = round(
            sum(entry.get("ai_likelihood", 0) for entry in classifications)
            / len(classifications),
            3,
        )

    return jsonify(
        {
            "classification_count": len(classifications),
            "appeal_count": len(appeals),
            "appeal_rate": round(len(appeals) / len(classifications), 3)
            if classifications
            else 0,
            "attribution_counts": attribution_counts,
            "average_ai_likelihood": average_ai_likelihood,
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
