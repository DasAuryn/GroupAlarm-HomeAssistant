import os
import json
from flask import Flask, render_template, jsonify
import requests

from run_state import load_ui_cache  

API_BASE    = os.getenv("API_BASE_URL", "").rstrip("/")
TOKEN       = os.getenv("TOKEN", "")
HEADER_NAME = os.getenv("HEADER_NAME", "Personal-Access-Token")
VERIFY_TLS  = (os.getenv("VERIFY_TLS", "true").lower() != "false")

app = Flask(__name__, template_folder="templates", static_folder=None)

def http(method: str, path: str, **kw):
    assert API_BASE, "API_BASE_URL missing"
    headers = kw.pop("headers", {})
    headers[HEADER_NAME] = TOKEN
    kw["headers"] = headers
    kw.setdefault("timeout", 15)
    kw.setdefault("verify", VERIFY_TLS)
    r = requests.request(method.upper(), f"{API_BASE}{path}", **kw)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text

def _get(cache: dict, section: str, key):
    """section ('names'/'actions'/'avatars') mit int- oder str-Key zuverlässig lesen."""
    d = cache.get(section, {})
    return d.get(key) if key in d else d.get(str(key), d.get(int(key), None))

@app.get("/")
def index():
    cache = load_ui_cache()
    order   = cache.get("order", []) or []
    names   = cache.get("names", {}) or {}
    actions = cache.get("actions", {}) or {}
    avatars = cache.get("avatars", {}) or {}

    orgs = []
    for oid in order:
        name    = _get(cache, "names", oid) or f"Org {oid}"
        avatar  = _get(cache, "avatars", oid) or ""
        acts    = _get(cache, "actions", oid) or []
        orgs.append({"id": oid, "name": name, "avatar": avatar, "actions": acts})

    empty = all((len(o["actions"]) == 0 for o in orgs)) and len(orgs) == 0
    return render_template("index.html", orgs=orgs, empty=empty)

@app.post("/press/<int:org_id>/<int:qa_id>")
def press(org_id: int, qa_id: int):

    cache = load_ui_cache()
    acts = _get(cache, "actions", org_id) or []
    qa = next((a for a in acts if isinstance(a, dict) and a.get("id") == qa_id), None)
    if not qa:
        return jsonify({"ok": False, "error": "qa_not_in_cache"}), 404

    res_type = qa.get("resource")
    res_id   = qa.get("resource_id")

    try:
        if res_type == "resource-template":
            body = {"organizationID": org_id, "alarmResourceTemplateID": res_id}
            http("POST", "/alarm", json=body)
            return jsonify({"ok": True})
        elif res_type == "tag":
            body = {"organizationID": org_id}
            http("POST", f"/tags/{res_id}/trigger", json=body)
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": "unsupported_resource", "resource": res_type}), 400
    except requests.HTTPError as e:
        return jsonify({"ok": False, "error": "http_error", "status": e.response.status_code, "text": e.response.text}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

