import json, threading, time, requests
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Body
import uvicorn
from datetime import datetime, timezone

from settings import *
STATE = {"last": {}, "actions": []}

def dtopic(kind, eid):
    base = f"{DISCOVERY_PREFIX}/{kind}/{DEVICE_ID}/{eid}"
    return {"cfg": f"{base}/config", "state": f"{base}/state", "cmd": f"{base}/set"}

def publish_discovery(client):
    device = {"identifiers":[DEVICE_ID], "manufacturer":"GroupAlarm", "name":DEVICE_NAME, "model":"REST Bridge"}

    for org in ORG_IDS or [PRIMARY_ORG_ID]:
        suffix = f"_org_{org}"
        sensors = [
            ("binary_sensor", f"shift_any_active{suffix}", {"name": f"Shift aktiv (Org {org})", "icon":"mdi:account-clock"}),
            ("sensor", f"active_shift_users{suffix}", {"name": f"Aktive Schicht-Nutzer (Org {org})", "unit_of_meas":"users", "icon":"mdi:account-group"}),
            ("sensor", f"open_events{suffix}", {"name": f"Offene Events (Org {org})", "icon":"mdi:calendar-clock"}),
            ("sensor", f"last_alarm_id{suffix}", {"name": f"Letzter Alarm ID (Org {org})"}),
            ("sensor", f"last_alarm_message{suffix}", {"name": f"Letzte Alarmmeldung (Org {org})"}),
            ("sensor", f"last_alarm_start{suffix}", {"name": f"Letzter Alarm Start (Org {org})", "device_class":"timestamp"}),
        ]
        for kind, eid, extra in sensors:
            t = dtopic(kind, eid)
            cfg = {"name": extra["name"], "uniq_id": f"{DEVICE_ID}_{eid}", "stat_t": t["state"], "dev": device}
            if "unit_of_meas" in extra: cfg["unit_of_meas"]=extra["unit_of_meas"]
            if "device_class" in extra: cfg["dev_cla"]=extra["device_class"]
            if "icon" in extra: cfg["icon"]=extra["icon"]
            client.publish(t["cfg"], json.dumps(cfg), qos=1, retain=True)

    for eid, name in [
        ("trigger_tag","Tag triggern"),
        ("create_alarm","Alarm erstellen"),
        ("close_event_by_external_id","Event schließen (ExtID)"),
        ("abort_event","Event abbrechen"),
    ]:
        t = dtopic("button", eid)
        cfg = {"name": name, "uniq_id": f"{DEVICE_ID}_{eid}", "cmd_t": t["cmd"], "dev": device, "icon":"mdi:play-circle"}
        client.publish(t["cfg"], json.dumps(cfg), qos=1, retain=True)

def http(session: requests.Session, path: str, params=None, method="GET", json_body=None):
    url = f"{API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    r = session.request(method, url, headers=auth_headers(), params=params, json=json_body, timeout=15, verify=VERIFY_TLS)
    r.raise_for_status()
    if "application/json" in r.headers.get("Content-Type",""):
        return r.json()
    return r.text

def to_iso(ts):
    if not ts: return None

    try:
        return datetime.fromisoformat(str(ts).replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return None

def poll_once(session, client):
    orgs = ORG_IDS or ([PRIMARY_ORG_ID] if PRIMARY_ORG_ID else [])
    for org in orgs:
        suffix = f"_org_{org}"

        try:
            data = http(session, f"/shift/any-active/{org}")
            any_active = bool(next((v for v in data.values() if isinstance(v,bool)), False)) if isinstance(data, dict) else False
        except Exception:
            any_active = False
        client.publish(dtopic("binary_sensor", f"shift_any_active{suffix}")["state"], "ON" if any_active else "OFF")

        try:
            au = http(session, f"/shift/active-users/{org}")
            users = len(au.get("users", [])) if isinstance(au, dict) else 0
        except Exception:
            users = 0
        client.publish(dtopic("sensor", f"active_shift_users{suffix}")["state"], str(users))

        try:
            events = http(session, "/events/open", params={"organization": org})
            open_count = len(events) if isinstance(events, list) else 0
        except Exception:
            open_count = 0
        client.publish(dtopic("sensor", f"open_events{suffix}")["state"], str(open_count))

        try:
            alarms = http(session, "/alarms", params={"organization": org, "limit": 1, "offset": 0})
            items = alarms.get("alarms", []) if isinstance(alarms, dict) else []
            if items:
                a = items[0]
                client.publish(dtopic("sensor", f"last_alarm_id{suffix}")["state"], str(a.get("id","")))
                client.publish(dtopic("sensor", f"last_alarm_message{suffix}")["state"], json.dumps(a.get("message","")))
                client.publish(dtopic("sensor", f"last_alarm_start{suffix}")["state"], to_iso(a.get("startDate")) or "")
        except Exception:
            pass

def resolve_org_id(body):
    org = body.get("organizationID") or body.get("organization_id") or PRIMARY_ORG_ID
    if not org:

        return (ORG_IDS[0] if ORG_IDS else None)
    return int(org)

def on_message(_cl, _ud, msg):

    if msg.topic == dtopic("button","trigger_tag")["cmd"]:
        tag_id = body.get("tag_id") or body.get("id") or DEFAULT_TAG_ID
        org = resolve_org_id(body)  
        if not tag_id: raise ValueError("tag_id fehlt")
        req = body.get("request") or {}
        http(session, f"/tags/{int(tag_id)}/trigger", method="POST", json_body=req)
        handle_action_result(client, True, f"Tag {tag_id} getriggert")

    elif msg.topic == dtopic("button","create_alarm")["cmd"]:
        req = body.get("request") or {}
        req.setdefault("organizationID", resolve_org_id(req) or PRIMARY_ORG_ID)
        http(session, "/alarm", method="POST", json_body=req)
        handle_action_result(client, True, "Alarm erstellt")

    elif msg.topic == dtopic("button","close_event_by_external_id")["cmd"]:
        ext = body.get("externalID") or DEFAULT_EVENT_EXTERNAL_ID
        org = resolve_org_id(body)
        if not ext: raise ValueError("externalID fehlt")
        if not org: raise ValueError("organizationID konnte nicht ermittelt werden")
        http(session, "/event/closeWithExternalID", method="PATCH", params={"externalID": ext, "organizationID": org})
        handle_action_result(client, True, f"Event extID={ext} geschlossen")

    elif msg.topic == dtopic("button","abort_event")["cmd"]:
        req = body.get("request") or {}
        http(session, "/events/abort", method="POST", json_body=req)
        handle_action_result(client, True, "Event abgebrochen")

def handle_action_result(client, ok: bool, msg: str):
    payload = {"ok": ok, "message": msg}
    client.publish(dtopic("sensor","last_action_result")["state"], json.dumps(payload), qos=0)

def start_mqtt(session):
    client = mqtt.Client(client_id=f"{DEVICE_ID}_bridge")
    if MQTT_USERNAME: client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.connect(MQTT_HOST, MQTT_PORT, 60)

    publish_discovery(client)

    def on_message(_cl, _ud, msg):
        try:
            body = json.loads(msg.payload.decode("utf-8")) if msg.payload else {}
        except Exception:
            body = {}

        try:
            if msg.topic == dtopic("button","trigger_tag")["cmd"]:
                tag_id = body.get("tag_id") or body.get("id") or os.environ.get("DEFAULT_TAG_ID")
                if not tag_id:
                    raise ValueError("tag_id fehlt (Payload: {\"tag_id\": 123, \"request\": {...}})")
                req = body.get("request") or {}
                http(session, f"/tags/{int(tag_id)}/trigger", method="POST", json_body=req)
                handle_action_result(client, True, f"Tag {tag_id} getriggert")
            elif msg.topic == dtopic("button","create_alarm")["cmd"]:
                req = body.get("request") or {}
                if "organizationID" not in req: req["organizationID"] = ORG_ID
                http(session, "/alarm", method="POST", json_body=req)
                handle_action_result(client, True, "Alarm erstellt")
            elif msg.topic == dtopic("button","close_event_by_external_id")["cmd"]:
                ext = body.get("externalID") or os.environ.get("DEFAULT_EVENT_EXTERNAL_ID")
                org = int(body.get("organizationID") or ORG_ID)
                if not ext: raise ValueError("externalID fehlt")
                http(session, "/event/closeWithExternalID", method="PATCH", params={"externalID": ext, "organizationID": org})
                handle_action_result(client, True, f"Event extID={ext} geschlossen")
            elif msg.topic == dtopic("button","abort_event")["cmd"]:
                req = body.get("request") or {}
                http(session, "/events/abort", method="POST", json_body=req)
                handle_action_result(client, True, "Event abgebrochen")
        except Exception as e:
            handle_action_result(client, False, str(e))

    for eid in ("trigger_tag","create_alarm","close_event_by_external_id","abort_event"):
        client.subscribe(dtopic("button",eid)["cmd"])

    client.on_message = on_message

    def loop():
        while True:
            try:
                poll_once(session, client)
            except Exception as e:
                handle_action_result(client, False, f"Polling error: {e}")
            time.sleep(POLL_INTERVAL)

    threading.Thread(target=loop, daemon=True).start()
    client.loop_forever()

app = FastAPI()

@app.get("/")
def root():
    return {
        "device": {"id": DEVICE_ID, "name": DEVICE_NAME},
        "org": ORG_ID,
        "poll_interval": POLL_INTERVAL,
        "last": STATE.get("last", {}),
        "actions": STATE.get("actions", [])
    }

def main():
    session = requests.Session()
    start_mqtt(session)
    uvicorn.run(app, host=INGRESS_HOST, port=INGRESS_PORT, log_level="info")

if __name__ == "__main__":
    main()