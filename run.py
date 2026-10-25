#!/usr/bin/env python3
import os, sys, json, time, pathlib, importlib.util
import math
from datetime import datetime, timezone
from typing import Dict, Any, List
import threading
from run_state import save_alarms_cache, load_alarms_cache, load_ui_cache

sys.path.insert(0, os.path.dirname(__file__) or "/")
try:
    import run_state
except ModuleNotFoundError:
    p = pathlib.Path(__file__).with_name("run_state.py")
    if not p.exists():
        raise
    spec = importlib.util.spec_from_file_location("run_state", str(p))
    run_state = importlib.util.module_from_spec(spec)
    sys.modules["run_state"] = run_state
    spec.loader.exec_module(run_state)  

from run_state import CACHE_LOCK, ACTIONS_CACHE, ORG_NAMES, save_ui_cache

API_BASE    = os.environ.get("API_BASE_URL", "").rstrip("/")
TOKEN       = os.environ.get("TOKEN", "")
HEADER_NAME = os.environ.get("HEADER_NAME", "Personal-Access-Token")
VERIFY_TLS  = (os.environ.get("VERIFY_TLS", "true").lower() != "false")

ORG_IDS     = [int(x) for x in os.environ.get("ORG_IDS", "").split(",") if x.strip().isdigit()]
PRIMARY     = int(os.environ.get("PRIMARY_ORG_ID", "0") or 0)
INTERVAL    = int(os.environ.get("POLL_INTERVAL", os.environ.get("POLL_INTERVAL_SEC", "30")))

MQTT_HOST   = os.environ.get("MQTT_HOST", "")
MQTT_PORT   = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER   = os.environ.get("MQTT_USERNAME", "")
MQTT_PASS   = os.environ.get("MQTT_PASSWORD", "")
DISCOVERY   = os.environ.get("DISCOVERY_PREFIX", "homeassistant")
DEVICE_NAME = os.environ.get("DEVICE_NAME", "GroupAlarm Bridge")
DEVICE_ID   = os.environ.get("DEVICE_ID", "groupalarm_bridge_1")
ALARM_POLL_SEC = int(os.environ.get("ALARM_POLL_SEC", "5"))
LAST_ALARM_IDS = {}
ALARM_RESET_SECONDS = int(os.environ.get("ALARM_RESET_SECONDS", "5"))
_last_alarm_published: dict[int, dict] = {}  # {org_id: {"id": int, "ts": epoch}}
_last_alarm_details: dict[int, dict] = {}
ALARM_DETAIL_SENSORS = (
    ("message", "Alarmmeldung", "mdi:message-text"),
    ("address", "Einsatzadresse", "mdi:map-marker"),
    ("coordinates", "Koordinaten", "mdi:crosshairs-gps"),
    ("event_id", "Einsatz-ID", "mdi:identifier"),
    ("event_name", "Einsatzstichwort", "mdi:alarm-light"),
    ("start_date", "Alarmierungszeitpunkt", "mdi:clock-outline"),
)


mqtt = None
have_mqtt = False

import requests
def fetch_latest_alarms_for_org(org_id: int) -> list[dict]:
    try:
        data = http("GET", f"/alarms", params={"organization": org_id})
        alarms = (data or {}).get("alarms") or []
        return alarms[:5]
    except Exception as e:
        print(json.dumps({"alarms_error": str(e), "org": org_id}), flush=True)
        return []

def refresh_alarms_every_5s():
    while True:
        try:
            live_ids, names_all, avatars_all = current_org_ids_and_names()
            target_orgs = live_ids or (ORG_IDS or ([PRIMARY] if PRIMARY else []))

            alarms_by_org = {}
            for oid in target_orgs:
                alarms = fetch_latest_alarms_for_org(oid)
                alarms_by_org[oid] = alarms

            save_ui_cache(alarms_by_org=alarms_by_org)
        except Exception as e:
            print(json.dumps({"alarms_loop_error": str(e)}), flush=True)
        time.sleep(5)
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

ICON_MAP = {
    "local_fire_department": "mdi:fire-alert",
    "medical_information": "mdi:medical-bag",
    "notifications": "mdi:bell",
    "engineering": "mdi:hard-hat",
    "security": "mdi:shield",
    "bolt": "mdi:flash",
    "groups": "mdi:account-group",
    "sos": "mdi:sos",
    "zoom_in_map": "mdi:map-marker-outline",
    "whatshot": "mdi:fire",
}

def quick_actions_for_org(org_id: int) -> List[dict]:
    try:
        data = http("GET", f"/organization/{org_id}/quick-actions")
        if isinstance(data, list):
            out = []
            for qa in data:
                if not isinstance(qa, dict):
                    continue
                out.append({
                    "id": qa.get("id"),
                    "organization_id": qa.get("organization_id"),
                    "name": qa.get("name"),
                    "color": qa.get("color"),
                    "icon": qa.get("icon"),
                    "one_click": qa.get("one_click"),
                    "resource": qa.get("resource"),
                    "resource_id": qa.get("resource_id"),
                    "category": qa.get("category"),
                })
            return out
    except Exception as e:
        print(json.dumps({"org": org_id, "quick_actions_error": str(e)}), flush=True)
    return []

def current_org_ids_and_names() -> tuple[list[int], dict[int, str], dict[int, str]]:
    try:
        orgs = http("GET", "/organizations")
    except Exception as e:
        print(json.dumps({"organizations_error": str(e)}), flush=True)
        return [], {}, {}
    ids: list[int] = []
    names: dict[int, str] = {}
    avatars: dict[int, str] = {}
    for o in orgs or []:
        if not isinstance(o, dict) or "id" not in o:
            continue
        oid = int(o["id"])
        ids.append(oid)
        names[oid] = o.get("name", f"Org {oid}")
        avatars[oid] = o.get("avatarURL") or ""
    return ids, names, avatars

def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode("utf-8", "ignore")
        prefix = f"{DISCOVERY}/{DEVICE_ID}/org/"
        if not topic.startswith(prefix):
            return

        parts = topic[len(prefix):].split("/")
        if len(parts) != 4 or parts[1] != "action" or parts[3] != "set":
            return
        org_id = int(parts[0]); qa_id = int(parts[2])
        if payload != "PRESS":
            return

        actions = quick_actions_for_org(org_id)
        qa = next((x for x in actions if x.get("id") == qa_id), None)
        if not qa:
            print(json.dumps({"press_error":"qa_not_found","org":org_id,"qa_id":qa_id}), flush=True)
            return

        res_type = qa.get("resource"); res_id = qa.get("resource_id")
        if res_type == "resource-template":
            body = {"organizationID": org_id, "alarmResourceTemplateID": res_id}
            try:
                resp = http("POST", "/alarm", json=body)
                print(json.dumps({"triggered":"alarm_from_template","org":org_id,"qa_id":qa_id,"resp":resp}), flush=True)
            except Exception as e:
                print(json.dumps({"trigger_error":"alarm_from_template","org":org_id,"qa_id":qa_id,"err":str(e)}), flush=True)
        elif res_type == "tag":
            body = {"organizationID": org_id}
            try:
                resp = http("POST", f"/tags/{res_id}/trigger", json=body)
                print(json.dumps({"triggered":"tag","org":org_id,"qa_id":qa_id,"resp":resp}), flush=True)
            except Exception as e:
                print(json.dumps({"trigger_error":"tag","org":org_id,"qa_id":qa_id,"err":str(e)}), flush=True)
        else:
            print(json.dumps({"press_ignored":"unsupported_resource","org":org_id,"qa_id":qa_id,"resource":res_type}), flush=True)
    except Exception as e:
        print(json.dumps({"mqtt_on_message_err":str(e)}), flush=True)

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        with CACHE_LOCK:
            _last_alarm_details.clear()
        org_ids = ORG_IDS or ([PRIMARY] if PRIMARY else (load_ui_cache() or {}).get("order", []))
        for org_id in org_ids:
            for field in ("latitude", "longitude"):
                client.publish(
                    f"{DISCOVERY}/sensor/{DEVICE_ID}/org{org_id}_alarm_{field}/config",
                    b"", qos=1, retain=True,
                )


def try_setup_mqtt():
    global mqtt, have_mqtt
    if not MQTT_HOST:
        return
    try:
        import paho.mqtt.client as paho
        mqtt = paho.Client(client_id=f"{DEVICE_ID}", protocol=paho.MQTTv311)
        if MQTT_USER or MQTT_PASS:
            mqtt.username_pw_set(MQTT_USER, MQTT_PASS)
        mqtt.on_connect = on_mqtt_connect
        mqtt.on_message = on_mqtt_message
        mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        mqtt.loop_start()
        have_mqtt = True
        run_state.mqtt_client = mqtt
        print(json.dumps({"mqtt":"connected","host":MQTT_HOST,"port":MQTT_PORT}), flush=True)
    except Exception as e:
        print(json.dumps({"mqtt_error":str(e)}), flush=True)

def mqtt_publish(topic, payload, retain=True):
    if not have_mqtt: return
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload, ensure_ascii=False)
    return mqtt.publish(topic, payload, qos=0, retain=retain)

def discovery_alarm_binary_sensor(org_id: int, org_name: str):
    if not have_mqtt: return
    uniq = f"{DEVICE_ID}_org{org_id}_alarm"
    topic_cfg = f"{DISCOVERY}/binary_sensor/{DEVICE_ID}/org{org_id}_alarm/config"
    state_topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/alarm"
    payload = {
        "name": f"{org_name} – Alarm",
        "unique_id": uniq,
        "device": {
            "identifiers": [DEVICE_ID],
            "name": DEVICE_NAME,
            "manufacturer": "GroupAlarm",
            "model": "REST Bridge",
        },
        "state_topic": state_topic,
        "value_template": "{{ 'ON' if value_json.active else 'OFF' }}",
        "json_attributes_topic": state_topic,
        "icon": "mdi:alarm-light",
        "visible_by_default": True,
    }
    mqtt_publish(topic_cfg, payload, retain=True)

def discovery_alarm_sensors(org_id: int, org_name: str):
    if not have_mqtt:
        return
    state_topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/alarm/details"
    for field, label, icon in ALARM_DETAIL_SENSORS:
        payload = {
            "name": f"{org_name} – {label}",
            "unique_id": f"{DEVICE_ID}_org{org_id}_alarm_{field}",
            "visible_by_default": False,
            "device": {
                "identifiers": [DEVICE_ID],
                "name": DEVICE_NAME,
                "manufacturer": "GroupAlarm",
                "model": "REST Bridge",
            },
            "state_topic": state_topic,
            "value_template": "{{ value_json." + field + " }}",
            "icon": icon,
        }
        if field in {"message", "address", "event_name"}:
            payload["value_template"] = (
                "{{ value_json." + field + "[:255] if value_json."
                + field + " is not none else none }}"
            )
            payload["json_attributes_topic"] = state_topic
            payload["json_attributes_template"] = (
                "{{ {'" + field + "': value_json." + field + "} | tojson }}"
            )
        elif field == "start_date":
            payload["device_class"] = "timestamp"
        elif field == "coordinates":
            payload["json_attributes_topic"] = state_topic
            payload["json_attributes_template"] = (
                "{{ {'latitude': value_json.latitude, 'longitude': value_json.longitude} | tojson }}"
            )
        mqtt_publish(
            f"{DISCOVERY}/sensor/{DEVICE_ID}/org{org_id}_alarm_{field}/config",
            payload,
            retain=True,
        )


def _positive_alarm_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def _alarm_coordinate(value, limit):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and abs(number) <= limit else None


def _alarm_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if date.tzinfo is not None:
            return date.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        pass
    return None


def alarm_details_payload(org_id: int, alarm: dict | None):
    alarm = alarm if isinstance(alarm, dict) else {}
    event = alarm.get("event")
    event = event if isinstance(event, dict) else {}
    optional = alarm.get("optionalContent")
    optional = optional if isinstance(optional, dict) else {}
    payload = {
        "organization_id": org_id,
        "alarm_id": _positive_alarm_id(alarm.get("id")),
        "event_id": (
            _positive_alarm_id(event.get("id"))
            or _positive_alarm_id(alarm.get("eventID"))
            or _positive_alarm_id(alarm.get("eventId"))
        ),
        "latitude": _alarm_coordinate(optional.get("latitude"), 90),
        "longitude": _alarm_coordinate(optional.get("longitude"), 180),
        "start_date": _alarm_timestamp(alarm.get("startDate")),
    }
    for field, value in (
        ("message", alarm.get("message")),
        ("address", optional.get("address")),
        ("event_name", event.get("name")),
    ):
        payload[field] = value if isinstance(value, str) and value.strip() else None
    latitude, longitude = payload["latitude"], payload["longitude"]
    payload["coordinates"] = (
        f"{latitude}, {longitude}" if latitude is not None and longitude is not None else None
    )
    return payload


def publish_alarm_details(org_id: int, alarm: dict | None):
    if not have_mqtt:
        return
    payload = alarm_details_payload(org_id, alarm)
    with CACHE_LOCK:
        if _last_alarm_details.get(org_id) == payload:
            return
        result = mqtt_publish(
            f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/alarm/details",
            payload,
            retain=True,
        )
        if result is not None and result.rc == 0:
            _last_alarm_details[org_id] = payload


def publish_alarm_state(org_id: int, alarm: dict | None, org_name: str):
    """
    Bei neuem Alarm: active:true + reichlich Attribute veröffentlichen.
    Nach Ablauf: active:false.
    """
    state_topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/alarm"

    if alarm is None:
        mqtt_publish(state_topic, {"active": False, "ts": int(time.time())}, retain=False)
        return

    ev = alarm.get("event")
    ev = ev if isinstance(ev, dict) else {}
    sev = ev.get("severity")
    sev = sev if isinstance(sev, dict) else {}
    opt = alarm.get("optionalContent")
    opt = opt if isinstance(opt, dict) else {}
    attrs = {
        "active": True,
        "id": alarm.get("id"),
        "message": alarm.get("message"),
        "startDate": alarm.get("startDate"),
        "organizationID": alarm.get("organizationID"),
        "event": {
            "id": ev.get("id"),
            "name": ev.get("name"),
            "severity": {
                "name": sev.get("name"),
                "level": sev.get("level"),
                "color": sev.get("color"),
                "icon": sev.get("icon"),
            },
        },
        "address": opt.get("address"),
        "latitude": opt.get("latitude"),
        "longitude": opt.get("longitude"),
        "creatorName": alarm.get("creatorName"),
        "creatorID": alarm.get("creatorID"),
    }
    mqtt_publish(state_topic, attrs, retain=False)

def discovery_quick_action_button(org_id: int, org_name: str, qa: dict):
    if not have_mqtt:
        return
    qa_id = qa.get("id")
    qa_name = qa.get("name", f"QAction {qa_id}")
    icon = ICON_MAP.get(qa.get("icon") or "", "mdi:gesture-tap-button")
    uniq = f"{DEVICE_ID}_org{org_id}_qa_{qa_id}"
    cfg_topic = f"{DISCOVERY}/button/{DEVICE_ID}/org{org_id}_qa{qa_id}/config"
    cmd_topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/action/{qa_id}/set"
    mqtt_publish(cfg_topic, {
        "name": f"{org_name} – {qa_name}",
        "unique_id": uniq,
        "device": {
            "identifiers": [DEVICE_ID],
            "name": DEVICE_NAME,
            "manufacturer": "GroupAlarm",
            "model": "REST Bridge",
        },
        "icon": icon,
        "entity_category": "config",
        "command_topic": cmd_topic,
        "payload_press": "PRESS",
        "visible_by_default": True,
    }, retain=True)

def discovery_quick_actions_for_org(org_id: int, org_name: str, actions: List[dict]):
    for qa in actions:
        discovery_quick_action_button(org_id, org_name, qa)

def mqtt_cleanup_org(org_id: int, actions: list[dict] | None = None):
    """Leert retained Configs, damit HA alte Button-Entities löscht."""
    if not have_mqtt:
        return
    if actions is None:
        actions = ACTIONS_CACHE.get(org_id, [])
    for qa in actions:
        qa_id = qa.get("id")
        cfg_topic = f"{DISCOVERY}/button/{DEVICE_ID}/org{org_id}_qa{qa_id}/config"
        mqtt.publish(cfg_topic, b"", qos=0, retain=True)
    for field, _label, _icon in ALARM_DETAIL_SENSORS:
        cfg_topic = f"{DISCOVERY}/sensor/{DEVICE_ID}/org{org_id}_alarm_{field}/config"
        mqtt.publish(cfg_topic, b"", qos=0, retain=True)
    details_topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/alarm/details"
    mqtt.publish(details_topic, b"", qos=0, retain=True)
    with CACHE_LOCK:
        _last_alarm_details.pop(org_id, None)
    st = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/state"
    mqtt.publish(st, b"", qos=0, retain=False)

def publish_quick_actions(org_id: int, actions: List[dict]):
    """Nur Log + optional ein Topic mit der Rohliste (kannst du für Debug nutzen)."""
    print(json.dumps({"org": org_id, "quick_actions": actions}, ensure_ascii=False), flush=True)
    if have_mqtt:
        topic = f"{DISCOVERY}/{DEVICE_ID}/org/{org_id}/quick_actions"
        mqtt.publish(topic, json.dumps(actions, ensure_ascii=False), qos=0, retain=True)

def refresh_all_quick_actions_and_discovery():
    live_ids, names_all, avatars_all = current_org_ids_and_names()
    target_orgs = live_ids or (ORG_IDS or ([PRIMARY] if PRIMARY else []))

    ui_actions: Dict[int, List[dict]] = {}
    seen: set[int] = set()

    for org in target_orgs:
        seen.add(org)
        actions = quick_actions_for_org(org)
        publish_quick_actions(org, actions)
        discovery_quick_actions_for_org(org, names_all.get(org, f"Org {org}"), actions)

        with CACHE_LOCK:
            ORG_NAMES[org] = names_all.get(org, f"Org {org}")
            ACTIONS_CACHE[org] = actions

        ui_actions[org] = actions

    if live_ids:
        with CACHE_LOCK:
            stale = [oid for oid in list(ACTIONS_CACHE.keys()) if oid not in seen]
        for oid in stale:
            try:
                mqtt_cleanup_org(oid, ACTIONS_CACHE.get(oid))
            except Exception as e:
                print(json.dumps({"cleanup_error": str(e), "org": oid}), flush=True)
            with CACHE_LOCK:
                ACTIONS_CACHE.pop(oid, None)
                ORG_NAMES.pop(oid, None)

    try:
        names_for_ui = {org: ORG_NAMES.get(org, f"Org {org}") for org in target_orgs}
        save_ui_cache(
            names=names_for_ui,
            actions_by_org=ui_actions,
            org_order=target_orgs,
            avatars={org: avatars_all.get(org, "") for org in target_orgs}
        )
        print(json.dumps(
            {"cache_file": "updated", "orgs": target_orgs,
             "counts": {str(k): len(v) for k, v in ui_actions.items()}},
            ensure_ascii=False
        ), flush=True)
    except Exception as e:
        print(json.dumps({"cache_file_error": str(e)}), flush=True)
def simplify_alarm(a: dict) -> dict:
    ev = a.get("event") or {}
    opt = a.get("optionalContent") or {}
    sev = (ev.get("severity") or {})
    return {
        "id": a.get("id"),
        "message": a.get("message"),
        "startDate": a.get("startDate"),
        "organizationID": a.get("organizationID"),
        "event": {
            "id": ev.get("id"),
            "name": ev.get("name"),
            "startDate": ev.get("startDate"),
            "severity": {
                "level": (sev.get("level")),
                "name": (sev.get("name")),
                "color": (sev.get("color")),
                "icon": (sev.get("icon")),
            }
        },
        "optionalContent": {
            "address": opt.get("address"),
            "latitude": opt.get("latitude"),
            "longitude": opt.get("longitude"),
        }
    }

def fetch_org_alarms(org_id: int) -> list[dict] | None:
    try:
        data = http("GET", f"/alarms?organization={org_id}")
        alarms = data.get("alarms") if isinstance(data, dict) else None
        if not isinstance(alarms, list) or any(not isinstance(alarm, dict) for alarm in alarms):
            raise ValueError("Invalid alarms response")
        return alarms
    except Exception as e:
        print(json.dumps({"alarms_error": str(e), "org": org_id}), flush=True)
        return None

def fetch_open_event_ids(org_id: int) -> set[int]:
    try:
        events = http("GET", "/events/open", params={"organization": org_id})
        if not isinstance(events, list):
            return set()
        ids: set[int] = set()
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id") or event.get("eventID") or event.get("eventId")
            try:
                ids.add(int(event_id))
            except (TypeError, ValueError):
                pass
        return ids
    except Exception as e:
        print(json.dumps({"open_events_error": str(e), "org": org_id}), flush=True)
        return set()

def annotate_alarm_event_status(alarms: list[dict], open_event_ids: set[int]) -> list[dict]:
    annotated = []
    for alarm in alarms:
        if not isinstance(alarm, dict):
            continue
        item = dict(alarm)
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        event_id = event.get("id") or item.get("eventID") or item.get("eventId")
        try:
            event_id_int = int(event_id)
        except (TypeError, ValueError):
            event_id_int = None

        if event_id_int is None:
            item["event_status"] = "unknown"
        elif event_id_int in open_event_ids:
            item["event_status"] = "open"
        else:
            item["event_status"] = "closed"
        annotated.append(item)
    return annotated
    

def alarm_poller_once(target_orgs: list[int]):
    ui = load_ui_cache() or {}
    names = ui.get("names", {})
    previous_by_org = (load_alarms_cache() or {}).get("by_org") or {}

    by_org: dict[int, list] = {}
    now = int(time.time())

    for org in target_orgs:
        org_name = names.get(org, f"Org {org}")
        discovery_alarm_binary_sensor(org, org_name)
        discovery_alarm_sensors(org, org_name)

        alarms = fetch_org_alarms(org)
        if alarms is None:
            by_org[org] = previous_by_org.get(str(org), previous_by_org.get(org, []))
            alarm_obj = None
        else:
            open_event_ids = fetch_open_event_ids(org)
            by_org[org] = annotate_alarm_event_status(alarms, open_event_ids)
            alarm_obj = max(
                (alarm for alarm in alarms if _positive_alarm_id(alarm.get("id"))),
                key=lambda alarm: _positive_alarm_id(alarm.get("id")),
                default=None,
            )
            publish_alarm_details(org, alarm_obj)

        latest_id = _positive_alarm_id(alarm_obj.get("id")) if alarm_obj else 0
        last = _last_alarm_published.get(org, {})
        last_id = int(last.get("id") or 0)
        last_ts = int(last.get("ts") or 0)

        if latest_id and latest_id != last_id:
            publish_alarm_state(org, alarm_obj, org_name)
            _last_alarm_published[org] = {"id": latest_id, "ts": now}

        elif last_id and (now - last_ts >= ALARM_RESET_SECONDS):
            publish_alarm_state(org, None, org_name)  # OFF
            _last_alarm_published[org] = {"id": last_id, "ts": now}  

    save_alarms_cache(by_org=by_org)
    print(json.dumps({"alarms_cache": "updated",
                      "counts": {str(k): len(v) for k, v in by_org.items()}},
                     ensure_ascii=False), flush=True)

def refresh_alarms_for_all_orgs():
    live_ids, names_all, avatars_all = current_org_ids_and_names()
    target_orgs = live_ids or (ORG_IDS or ([PRIMARY] if PRIMARY else []))
    alarms_by_org: dict[int, list[dict]] = {}
    for oid in target_orgs:
        alarms = fetch_org_alarms(oid)
        if alarms is None:
            previous_by_org = (load_alarms_cache() or {}).get("by_org") or {}
            alarms_by_org[oid] = previous_by_org.get(str(oid), previous_by_org.get(oid, []))
            continue
        open_event_ids = fetch_open_event_ids(oid)
        alarms_by_org[oid] = annotate_alarm_event_status(alarms, open_event_ids)

    try:
       save_alarms_cache(by_org=alarms_by_org)
       print(json.dumps({"alarms_cache": "updated",
                          "counts": {str(k): len(v) for k, v in alarms_by_org.items()}}, ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({"alarms_cache_error": str(e)}), flush=True)

def discovery_for_org(org_id: int, org_name: str) -> None:
    return        

def ensure_discovery():
    if not have_mqtt:
        return
    try:
        orgs = http("GET", "/organizations")
        names = {int(o["id"]): o.get("name", f"Org {o['id']}") for o in orgs if isinstance(o, dict) and "id" in o}
    except Exception as e:
        print(json.dumps({"discovery_orgs_error": str(e)}), flush=True)
        names = {}

    target_orgs = ORG_IDS or ([PRIMARY] if PRIMARY else [])
    if not target_orgs:
        target_orgs = list(names.keys())

    for oid in target_orgs:
        discovery_for_org(oid, names.get(oid, f"Org {oid}"))


def ensure_mqtt_subscribe():
    if not have_mqtt:
        return
    topic = f"{DISCOVERY}/{DEVICE_ID}/org/+/action/+/set"
    try:
        mqtt.subscribe(topic, qos=0)
        mqtt.on_message = on_mqtt_message  
    except Exception as e:
        print(json.dumps({"mqtt_subscribe_error": str(e), "topic": topic}), flush=True)

if __name__ == "__main__":
    try_setup_mqtt()
    refresh_all_quick_actions_and_discovery()

    i = 0
    while True:
        if i % 6 == 0:  
            refresh_all_quick_actions_and_discovery()

        target_orgs = ORG_IDS or ([PRIMARY] if PRIMARY else [])
        if not target_orgs:
            ui = load_ui_cache() or {}
            target_orgs = ui.get("order", []) or sorted((ui.get("names") or {}).keys())

        alarm_poller_once(target_orgs)

        i += 1
        time.sleep(5) 
