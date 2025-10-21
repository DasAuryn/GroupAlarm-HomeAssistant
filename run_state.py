import json, os, threading, time

UI_CACHE_FILE = "/data/ui_cache.json"

CACHE_LOCK   = threading.Lock()
ACTIONS_CACHE = {}   
ORG_NAMES     = {}   
mqtt_client   = None

def save_ui_cache(names: dict[int, str], actions_by_org: dict[int, list], org_order: list[int], avatars: dict[int, str] | None = None):
    data = {
        "names": names,
        "actions": actions_by_org,
        "order": org_order,
        "avatars": avatars or {},
        "ts": int(time.time())
    }
    tmp = UI_CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, UI_CACHE_FILE)


def load_ui_cache():
    try:
        with open(UI_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"names": {}, "actions": {}, "order": [], "avatars": {}}