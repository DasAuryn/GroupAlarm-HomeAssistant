# web/__init__.py
import os, json
from flask import Flask, render_template, request, abort
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
    data = load_alarms_cache() or {}
    by_org = data.get("by_org", {})
    org_ids = [oid for oid, lst in by_org.items() if lst] or sorted(by_org.keys())
    alarms = [{"org_id": oid, "items": by_org.get(oid, [])} for oid in org_ids]
    return render_template("alarms.html", alarms=alarms, active_tab="alarms")
