# web/__init__.py
import os, json, time
from flask import Flask, render_template, jsonify, send_from_directory, redirect, url_for
from run_state import load_ui_cache

HERE = os.path.dirname(__file__)
TEMPLATES = os.path.join(HERE, "templates")
STATIC = os.path.join(HERE, "static")

app = Flask(__name__, template_folder=TEMPLATES, static_folder=STATIC)

@app.get("/")
def index():
    cache = load_ui_cache()
    names = cache.get("names", {})
    order = cache.get("order", [])
    actions_by_org = cache.get("actions", {})
    avatars = cache.get("avatars", {})

    ordered = [(oid, names.get(str(oid)) or names.get(oid) or f"Org {oid}", actions_by_org.get(str(oid)) or actions_by_org.get(oid) or []) for oid in order]
    return render_template("index.html",
                           names=names, org_actions=ordered, avatars=avatars,
                           active_tab="dashboard")

@app.get("/alarms")
def alarms_page():
    cache = load_ui_cache()
    names = cache.get("names", {})
    alarms_all = cache.get("alarms", {}) or {}

    flat = []
    for k, lst in (alarms_all.items() if isinstance(alarms_all, dict) else []):
        pass  
    if isinstance(alarms_all, dict):
        for org_id_str, lst in alarms_all.items():
            try:
                org_id = int(org_id_str)
            except:
                continue
            org_name = names.get(org_id_str) or names.get(org_id) or f"Org {org_id}"
            for a in (lst or []):
                aid = a.get("id")
                msg = a.get("message") or ""
                start = a.get("startDate") or a.get("event", {}).get("startDate")
                event_name = (a.get("event") or {}).get("name", "")
                sev = (a.get("event") or {}).get("severity") or {}
                sev_color = sev.get("color") or "#888888"

                lat = lon = None
                opt = a.get("optionalContent") or {}
                if isinstance(opt, dict):
                    lat = opt.get("latitude")
                    lon = opt.get("longitude")
                    try:
                        lat = float(lat) if lat is not None else None
                        lon = float(lon) if lon is not None else None
                    except Exception:
                        lat = lon = None

                flat.append({
                    "id": aid,
                    "org_id": org_id,
                    "org_name": org_name,
                    "message": msg,
                    "event_name": event_name,
                    "startDate": start,
                    "lat": lat,
                    "lon": lon,
                    "sev_color": sev_color,
                })

    def sort_key(x):
        return x.get("startDate") or ""
    flat.sort(key=sort_key, reverse=True)

    return render_template("alarms.html",
                           alarms=flat,
                           active_tab="alarms")

@app.get("/api/alarms")
def alarms_api():
    cache = load_ui_cache()
    return jsonify({
        "names": cache.get("names", {}),
        "alarms": cache.get("alarms", {}),
        "ts": int(time.time())
    })

@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC, filename)
