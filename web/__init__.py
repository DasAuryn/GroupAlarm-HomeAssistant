# web/__init__.py
import os
import requests
from flask import Flask, render_template, redirect, url_for, jsonify

from run_state import load_ui_cache, load_alarms_cache

API_BASE    = os.environ.get("API_BASE_URL", "").rstrip("/")
TOKEN       = os.environ.get("TOKEN", "")
HEADER_NAME = os.environ.get("HEADER_NAME", "Personal-Access-Token")
VERIFY_TLS  = (os.environ.get("VERIFY_TLS", "true").lower() != "false")

def http(method: str, path: str, **kw):
    if not API_BASE:
        raise RuntimeError("API_BASE_URL missing")
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

def quick_actions_for_org(org_id: int):
    try:
        data = http("GET", f"/organization/{org_id}/quick-actions")
        return [qa for qa in data if isinstance(qa, dict)]
    except Exception:
        return []

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.get("/")
def index():
    ui = load_ui_cache() or {}
    names = ui.get("names", {})
    avatars = ui.get("avatars", {})

    alarms_data = load_alarms_cache() or {}
    by_org = alarms_data.get("by_org", {})
    order = [oid for oid, lst in by_org.items() if lst] or sorted(by_org.keys())

    items = []
    for oid in order:
        items.append({
            "id": oid,
            "name": names.get(oid, f"Org {oid}"),
            "avatar": avatars.get(oid, ""),
            "alarms": by_org.get(oid, []),
        })
    return render_template("alarms.html", orgs=items, active_tab="alarms")


@app.get("/dashboard")
def dashboard():
    data = load_ui_cache() or {}
    names   = data.get("names", {})
    actions = data.get("actions", {})
    order   = data.get("order", [])
    avatars = data.get("avatars", {})
    if not order:
        order = sorted(actions.keys())
    orgs = []
    for oid in order:
        orgs.append({
            "id": oid,
            "name": names.get(oid, f"Org {oid}"),
            "avatar": avatars.get(oid, ""),
            "actions": actions.get(oid, []),
        })
    return render_template("index.html", orgs=orgs, active_tab="dashboard")

@app.get("/alarms")
def alarms_page():
    ui = load_ui_cache() or {}
    names = ui.get("names", {})
    avatars = ui.get("avatars", {})

    alarms_data = load_alarms_cache() or {}
    by_org = alarms_data.get("by_org", {})
    order = [oid for oid, lst in by_org.items() if lst] or sorted(by_org.keys())

    items = []
    for oid in order:
        items.append({
            "id": oid,
            "name": names.get(oid, f"Org {oid}"),
            "avatar": avatars.get(oid, ""),
            "alarms": by_org.get(oid, []),
        })
    return render_template("alarms.html", orgs=items, active_tab="alarms")

@app.post("/press/<int:org_id>/<int:qa_id>")
def press(org_id: int, qa_id: int):
    try:
        qas = quick_actions_for_org(org_id)
        qa  = next((q for q in qas if q.get("id") == qa_id), None)
        if not qa:
            return jsonify({"ok": False, "error": "Quick Action nicht gefunden"}), 404

        res_type = qa.get("resource")
        res_id   = qa.get("resource_id")

        if res_type == "resource-template":
            body = {"organizationID": org_id, "alarmResourceTemplateID": res_id}
            resp = http("POST", "/alarm", json=body)
            return jsonify({"ok": True, "type": "alarm_from_template", "resp": resp}), 200

        elif res_type == "tag":
            body = {"organizationID": org_id}
            resp = http("POST", f"/tags/{res_id}/trigger", json=body)
            return jsonify({"ok": True, "type": "tag_trigger", "resp": resp}), 200

        return jsonify({"ok": False, "error": f"Unsupported resource: {res_type}"}), 400

    except requests.HTTPError as e:
        return jsonify({"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
