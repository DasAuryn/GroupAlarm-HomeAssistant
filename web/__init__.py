# web/__init__.py
from flask import Flask, render_template
from run_state import load_ui_cache, load_alarms_cache

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.get("/")
def index():
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
