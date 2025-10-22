import json, os, time, hashlib, threading

UI_CACHE_FILE = "/data/ga_ui_cache.json"
ALARMS_CACHE_FILE = "/data/ga_alarms_cache.json"

CACHE_LOCK = threading.RLock()
ACTIONS_CACHE = {}
ORG_NAMES = {}


def _digest_alarms(by_org: dict) -> str:
    norm = json.dumps(by_org or {}, sort_keys=True, separators=(",", ":")).encode("utf-8", "ignore")
    return hashlib.sha1(norm).hexdigest()

def _to_int_keys(d):
    return {int(k): v for k, v in d.items()} if isinstance(d, dict) else {}

def save_ui_cache(*, names: dict, actions_by_org: dict, org_order: list[int], avatars: dict):
    payload = {
        "names": names,
        "actions": actions_by_org,
        "order": org_order,
        "avatars": avatars,
        "ts": int(time.time()),
    }
    tmp = UI_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, UI_CACHE_FILE)

def load_ui_cache():
    try:
        with open(UI_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw["names"]   = _to_int_keys(raw.get("names", {}))
        raw["actions"] = _to_int_keys(raw.get("actions", {}))
        raw["avatars"] = _to_int_keys(raw.get("avatars", {}))
        raw["order"]   = [int(x) for x in raw.get("order", [])]
        return raw
    except Exception:
        return {}

def load_alarms_cache():
    try:
        with open(ALARMS_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_alarms_cache(*, by_org: dict):
    with CACHE_LOCK:
        old = load_alarms_cache() or {}
        old_by_org = old.get("by_org") or {}
        old_sig = old.get("sig") or _digest_alarms(old_by_org)
        new_sig = _digest_alarms(by_org)

        if new_sig == old_sig:
            return False

        data = {
            "by_org": by_org,
            "ts": int(time.time()),
            "sig": new_sig,
        }
        tmp = ALARMS_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, ALARMS_CACHE_FILE)
        return True
