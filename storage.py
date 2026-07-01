import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CONTENT_STORE_PATH = DATA_DIR / "content_store.json"
AUDIT_LOG_PATH = DATA_DIR / "audit_log.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_data_files():
    DATA_DIR.mkdir(exist_ok=True)
    if not CONTENT_STORE_PATH.exists():
        CONTENT_STORE_PATH.write_text("{}", encoding="utf-8")
    if not AUDIT_LOG_PATH.exists():
        AUDIT_LOG_PATH.write_text("[]", encoding="utf-8")


def read_json(path, default):
    ensure_data_files()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError):
        return default


def write_json(path, value):
    ensure_data_files()
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def load_content_store():
    return read_json(CONTENT_STORE_PATH, {})


def save_content_store(store):
    write_json(CONTENT_STORE_PATH, store)


def create_content_record(content_id, creator_id, text, text_hash, analysis):
    store = load_content_store()
    record = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text_preview": text[:240],
        "text_hash": text_hash,
        "status": "classified",
        "created_at": utc_now(),
        "decision": {
            "attribution": analysis["attribution"],
            "confidence": analysis["confidence"],
            "ai_likelihood": analysis["ai_likelihood"],
            "label": analysis["label"],
            "signal_scores": {
                signal["name"]: signal["score"] for signal in analysis["signals"]
            },
        },
        "appeals": [],
    }
    store[content_id] = record
    save_content_store(store)
    return record


def get_content_record(content_id):
    return load_content_store().get(content_id)


def add_appeal(content_id, creator_reasoning):
    store = load_content_store()
    record = store.get(content_id)
    if not record:
        return None

    appeal = {
        "timestamp": utc_now(),
        "creator_reasoning": creator_reasoning,
        "status": "under_review",
    }
    record["status"] = "under_review"
    record.setdefault("appeals", []).append(appeal)
    store[content_id] = record
    save_content_store(store)
    return record


def append_audit_entry(entry):
    log = read_json(AUDIT_LOG_PATH, [])
    complete_entry = {"timestamp": utc_now(), **entry}
    log.append(complete_entry)
    write_json(AUDIT_LOG_PATH, log)
    return complete_entry


def recent_audit_entries(limit=10):
    log = read_json(AUDIT_LOG_PATH, [])
    return log[-limit:]


def all_audit_entries():
    return read_json(AUDIT_LOG_PATH, [])
