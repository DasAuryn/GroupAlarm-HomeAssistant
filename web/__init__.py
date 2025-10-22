# web/__init__.py
from flask import Flask, render_template, redirect, url_for, jsonify
from run_state import load_ui_cache, load_alarms_cache, trigger_quick_action

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.get("/")
def index():
    ui      = load_ui_cache() or {}
    names   = ui.get("names", {})
    avatars = ui.get("avatars", {})

    alarms_data = load_alarms_cache() or {}
    by_org      = alarms_data.get("by_org", {})
    order = [oid for oid, lst in by_org.items() if lst] or sorted(by_org.keys())

    items = [{
        "id": oid,
        "name": names.get(oid, f"Org {oid}"),
        "avatar": avatars.get(oid, ""),
        "alarms": by_org.get(oid, []),
    } for oid in order]
    return render_template("alarms.html", orgs=items, active_tab="alarms")

@app.get("/dashboard")
def dashboard_page():
    data    = load_ui_cache() or {}
    names   = data.get("names", {})
    actions = data.get("actions", {})
    order   = data.get("order", []) or sorted(actions.keys())
    avatars = data.get("avatars", {})

    orgs = [{
        "id": oid,
        "name": names.get(oid, f"Org {oid}"),
        "avatar": avatars.get(oid, ""),
        "actions": actions.get(oid, []),
    } for oid in order]
    return render_template("index.html", orgs=orgs, active_tab="dashboard")

@app.post("/press/<int:org_id>/<int:qa_id>")
def press(org_id, qa_id):
    try:
        ok, detail = trigger_quick_action(org_id, qa_id)
        return jsonify({"ok": ok, "detail": detail}), (200 if ok else 500)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500