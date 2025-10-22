# web/__init__.py
import os
import requests
from flask import Flask, render_template, redirect, url_for, jsonify
import json, hashlib

from run_state import load_ui_cache, load_alarms_cache, ORG_NAMES

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

@app.get("/alarms.json")
def alarms_json():
    data = load_alarms_cache() or {}
    by_org = data.get("by_org") or {}


    norm = json.dumps(by_org, sort_keys=True, separators=(",", ":")).encode("utf-8", "ignore")
    sig = hashlib.sha1(norm).hexdigest()

    counts = {str(k): len(v) for k, v in by_org.items()}
    return jsonify({"sig": sig, "counts": counts})


@app.get("/")
def index():
    return redirect(url_for("alarms_page"))


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
    names_raw   = ui.get("names", {})    
    avatars_raw = ui.get("avatars", {})  

    alarms_data = load_alarms_cache() or {}
    by_org_raw  = alarms_data.get("by_org", {}) 

    def to_int_keys(d):
        out = {}
        if not d:
            return out
        for k, v in d.items():
            try:
                out[int(k)] = v
            except (ValueError, TypeError):
                out[k] = v
        return out

    names   = to_int_keys(names_raw)
    avatars = to_int_keys(avatars_raw)
    by_org  = to_int_keys(by_org_raw)

    for k, v in ORG_NAMES.items():
        names.setdefault(k, v)

    missing = [oid for oid in by_org.keys() if oid not in names]
    if missing:
        try:
            orgs = http("GET", "/organizations")
            if isinstance(orgs, list):
                for o in orgs:
                    if isinstance(o, dict) and "id" in o:
                        oid = int(o["id"])
                        if oid in by_org and oid not in names:
                            names[oid] = o.get("name", f"Org {oid}")
                        if oid not in avatars:
                            avatars[oid] = o.get("avatarURL") or ""
        except Exception:
            pass  

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
