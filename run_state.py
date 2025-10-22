import json, os, threading, time

UI_CACHE_FILE = "/data/ui_cache.json"

CACHE_LOCK   = threading.Lock()
ACTIONS_CACHE = {}   
ORG_NAMES     = {}   
mqtt_client   = None

def merge_ui_cache(existing: dict, *, names=None, actions=None, order=None, avatars=None, alarms=None):
    out = dict(existing or {})
    if names  is not None:  out["names"]   = names
    if actions is not None: out["actions"] = actions
    if order  is not None:  out["order"]   = order
    if avatars is not None: out["avatars"] = avatars
    if alarms is not None:  out["alarms"]  = alarms
    out["ts"] = int(time.time())
    return out

def save_ui_cache(*, names=None, actions_by_org=None, org_order=None, avatars=None, alarms_by_org=None):
    try:
        current = load_ui_cache()
    except Exception:
        current = {}
    payload = merge_ui_cache(
        current,
        names=names if names is not None else current.get("names"),
        actions=actions_by_org if actions_by_org is not None else current.get("actions"),
        order=org_order if org_order is not None else current.get("order"),
        avatars=avatars if avatars is not None else current.get("avatars"),
        alarms=alarms_by_org if alarms_by_org is not None else current.get("alarms"),
    )
    tmp = UI_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, UI_CACHE_FILE)

def load_latest_alarms() -> dict:
    try:
        data = load_ui_cache()
        return data.get("alarms") or {}
    except Exception:
        return {}


def load_ui_cache():
    try:
        with open(UI_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"names": {}, "actions": {}, "order": [], "avatars": {}, "alarms": {}}