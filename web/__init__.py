# web/__init__.py
import colorsys
import os
import re
import requests
from flask import Flask, render_template, jsonify
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

def _list_length(value):
    return len(value) if isinstance(value, list) else 0


_HEX_COLOR_PATTERN = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_MATERIAL_ICON_PATTERN = re.compile(r"^[a-z0-9_]{3,64}$")
_QUICK_ACTION_FALLBACK_COLORS = {
    "resource-template": "#ef4d5d",
    "tag": "#397fd8",
}


def _parse_hex_color(value):
    if not isinstance(value, str):
        return None
    match = _HEX_COLOR_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(character * 2 for character in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def _color_to_hex(color):
    return "#{:02x}{:02x}{:02x}".format(*(round(channel) for channel in color))


def _blend_colors(foreground, background, foreground_weight):
    return tuple(
        foreground[index] * foreground_weight + background[index] * (1 - foreground_weight)
        for index in range(3)
    )


def _quick_action_palette(color_value, resource):
    """Adapt a GroupAlarm color to the dark UI instead of using it verbatim."""
    source = _parse_hex_color(color_value)
    if source is None:
        source = _parse_hex_color(
            _QUICK_ACTION_FALLBACK_COLORS.get(resource, "#8291a5")
        )

    hue, _lightness, saturation = colorsys.rgb_to_hls(
        *(channel / 255 for channel in source)
    )
    if saturation < 0.08:
        adapted_saturation = 0
    else:
        adapted_saturation = min(0.78, max(0.38, saturation * 0.72))
    adapted = tuple(
        channel * 255
        for channel in colorsys.hls_to_rgb(hue, 0.68, adapted_saturation)
    )

    return {
        "accent": _color_to_hex(adapted),
        "border": _color_to_hex(_blend_colors(adapted, (52, 71, 96), 0.55)),
        "surface": _color_to_hex(_blend_colors(adapted, (18, 31, 47), 0.16)),
    }


def _decorate_quick_action(action):
    item = dict(action)
    icon = item.get("icon")
    if isinstance(icon, str):
        icon = icon.strip().lower()
    item["ui_icon"] = icon if icon and _MATERIAL_ICON_PATTERN.fullmatch(icon) else ""
    item["ui_palette"] = _quick_action_palette(item.get("color"), item.get("resource"))
    return item


def _panel_content_key(items):
    """Return a stable key so a newly arrived item re-opens its organization."""
    markers = []
    for index, item in enumerate(items if isinstance(items, list) else []):
        if isinstance(item, dict):
            markers.append({
                "id": item.get("id", index),
                "status": item.get("event_status"),
                "name": item.get("name"),
                "color": item.get("color"),
                "icon": item.get("icon"),
                "resource": item.get("resource"),
            })
        else:
            markers.append({"index": index})
    normalized = json.dumps(markers, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()[:12]

app = Flask(__name__, template_folder="templates", static_folder="static")

@app.get("/alarms.json")
def alarms_json():
    data = load_alarms_cache() or {}
    by_org = data.get("by_org") or {}


    norm = json.dumps(by_org, sort_keys=True, separators=(",", ":")).encode("utf-8", "ignore")
    sig = hashlib.sha1(norm).hexdigest()

    counts = {str(k): _list_length(v) for k, v in by_org.items()}
    return jsonify({"sig": sig, "counts": counts})

def _build_alarms_items():
    ui = load_ui_cache() or {}
    names_raw   = ui.get("names", {})
    avatars_raw = ui.get("avatars", {})
    order_raw   = ui.get("order", [])

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

    known_ids = set(names) | set(avatars) | set(by_org)
    configured_order = []
    for oid in order_raw or []:
        try:
            normalized_id = int(oid)
        except (TypeError, ValueError):
            normalized_id = oid
        if normalized_id in known_ids and normalized_id not in configured_order:
            configured_order.append(normalized_id)

    remaining_ids = sorted(
        (oid for oid in known_ids if oid not in configured_order),
        key=lambda oid: str(names.get(oid, f"Org {oid}")).casefold(),
    )
    order = configured_order + remaining_ids

    items = []
    for oid in order:
        alarms = by_org.get(oid, [])
        if not isinstance(alarms, list):
            alarms = []
        alarms = [alarm for alarm in alarms if isinstance(alarm, dict)]
        items.append({
            "id": oid,
            "name": names.get(oid, f"Org {oid}"),
            "avatar": avatars.get(oid, ""),
            "alarms": alarms,
            "open_alarms": [a for a in alarms if (a or {}).get("event_status") == "open"],
            "closed_alarms": [a for a in alarms if (a or {}).get("event_status") == "closed"],
            "unknown_alarms": [a for a in alarms if (a or {}).get("event_status") not in ("open", "closed")],
        })
    return items

def _navigation_counts(alarm_items=None, quick_action_orgs=None):
    if alarm_items is None:
        alarm_items = _build_alarms_items()

    open_count = sum(
        _list_length(org.get("open_alarms")) + _list_length(org.get("unknown_alarms"))
        for org in alarm_items
    )
    closed_count = sum(_list_length(org.get("closed_alarms")) for org in alarm_items)

    if quick_action_orgs is None:
        action_values = (load_ui_cache() or {}).get("actions", {}).values()
        quick_actions_count = sum(_list_length(actions) for actions in action_values)
    else:
        quick_actions_count = sum(_list_length(org.get("actions")) for org in quick_action_orgs)

    return {
        "alarms_open": open_count,
        "alarms_closed": closed_count,
        "dashboard": quick_actions_count,
    }

@app.get("/")
def index():
    return alarms_open_page()


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
        raw_actions = actions.get(oid, [])
        if not isinstance(raw_actions, list):
            raw_actions = []
        org_actions = [
            _decorate_quick_action(action)
            for action in raw_actions
            if isinstance(action, dict)
        ]
        orgs.append({
            "id": oid,
            "name": names.get(oid, f"Org {oid}"),
            "avatar": avatars.get(oid, ""),
            "actions": org_actions,
            "panel_content_key": _panel_content_key(org_actions),
        })
    return render_template(
        "index.html",
        orgs=orgs,
        active_tab="dashboard",
        navigation_counts=_navigation_counts(quick_action_orgs=orgs),
    )

@app.get("/alarms")
def alarms_page():
    return alarms_open_page()

@app.get("/open")
@app.get("/alarms/open")
def alarms_open_page():
    items = _build_alarms_items()
    for org in items:
        org["display_alarms"] = org.get("open_alarms", []) + org.get("unknown_alarms", [])
        org["panel_content_key"] = _panel_content_key(org["display_alarms"])
    items.sort(key=lambda org: not bool(org.get("display_alarms")))
    return render_template(
        "alarms.html",
        orgs=items,
        active_tab="alarms_open",
        alarm_view="open",
        navigation_counts=_navigation_counts(alarm_items=items),
    )

@app.get("/closed")
@app.get("/alarms/closed")
def alarms_closed_page():
    items = _build_alarms_items()
    for org in items:
        org["display_alarms"] = org.get("closed_alarms", [])
        org["panel_content_key"] = _panel_content_key(org["display_alarms"])
    items.sort(key=lambda org: not bool(org.get("display_alarms")))
    return render_template(
        "alarms.html",
        orgs=items,
        active_tab="alarms_closed",
        alarm_view="closed",
        navigation_counts=_navigation_counts(alarm_items=items),
    )



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
