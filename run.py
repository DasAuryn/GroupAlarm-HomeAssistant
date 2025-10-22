#!/usr/bin/env python3
import os, sys, json, time, pathlib, importlib.util
from typing import Dict, Any, List
import threading

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

def try_setup_mqtt():
    global mqtt, have_mqtt
    if not MQTT_HOST:
        return
    try:
        import paho.mqtt.client as paho
        mqtt = paho.Client(client_id=f"{DEVICE_ID}", protocol=paho.MQTTv311)
        if MQTT_USER or MQTT_PASS:
            mqtt.username_pw_set(MQTT_USER, MQTT_PASS)
        mqtt.on_message = on_mqtt_message
        mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        mqtt.loop_start()
        have_mqtt = True
        run_state.mqtt_client = mqtt
        print(json.dumps({"mqtt":"connected","host":MQTT_HOST,"port":MQTT_PORT}), flush=True)
    except Exception as e:
        print(json.dumps({"mqtt_error":str(e)}), flush=True)

def mqtt_publish(topic: str, payload: Dict[str,Any], retain: bool = True):
    if not have_mqtt:
        return
    mqtt.publish(topic, json.dumps(payload, ensure_ascii=False), qos=0, retain=retain)

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
        "command_topic": cmd_topic,
        "payload_press": "PRESS",
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

def fetch_org_alarms(org_id: int) -> list[dict]:
    try:
        data = http("GET", f"/alarms?organization={org_id}")
        raw = (data or {}).get("alarms") or []
        return [simplify_alarm(a) for a in raw]
    except Exception as e:
        print(json.dumps({"alarms_error": str(e), "org": org_id}), flush=True)
        return []

def refresh_alarms_for_all_orgs():
    live_ids, names_all, avatars_all = current_org_ids_and_names()
    target_orgs = live_ids or (ORG_IDS or ([PRIMARY] if PRIMARY else []))
    alarms_by_org: dict[int, list[dict]] = {}
    for oid in target_orgs:
        alarms_by_org[oid] = fetch_org_alarms(oid)

    try:
        save_ui_cache(alarms_by_org=alarms_by_org)
        print(json.dumps({
            "alarms_cache": "updated",
            "counts": {str(k): len(v or []) for k, v in alarms_by_org.items()}
        }, ensure_ascii=False), flush=True)
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
    ensure_discovery()
    ensure_mqtt_subscribe()

    refresh_all_quick_actions_and_discovery()
    refresh_alarms_for_all_orgs()

    t_next_actions = time.monotonic() + max(5, INTERVAL)
    t_next_alarms  = time.monotonic() + max(1, ALARM_POLL_SEC)

    while True:
        now = time.monotonic()

        if now >= t_next_alarms:
            refresh_alarms_for_all_orgs()
            t_next_alarms = now + max(1, ALARM_POLL_SEC)

        if now >= t_next_actions:
            refresh_all_quick_actions_and_discovery()
            t_next_actions = now + max(5, INTERVAL)

        time.sleep(0.5)
