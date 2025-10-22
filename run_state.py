# run_state.py
import json, os, time, threading

UI_CACHE_FILE = "/data/ga_ui_cache.json"
ALARMS_CACHE_FILE = "/data/ga_alarms_cache.json"

CACHE_LOCK = threading.RLock()
ACTIONS_CACHE = {}
ORG_NAMES = {}

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

def _to_int_keys(d):
    return {int(k): v for k, v in d.items()} if isinstance(d, dict) else {}

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

def save_alarms_cache(*, by_org: dict[int, list]):
    payload = {"by_org": by_org, "ts": int(time.time())}
    tmp = ALARMS_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, ALARMS_CACHE_FILE)

def load_alarms_cache():
    try:
        with open(ALARMS_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw["by_org"] = _to_int_keys(raw.get("by_org", {}))
        return raw
    except Exception:
        return {}
