import os

API_BASE_URL = os.environ.get("API_BASE_URL", "https://app.groupalarm.com/api/v1")
TOKEN = os.environ.get("TOKEN", "")
USER_ID = int(os.environ.get("USER_ID", "0"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
VERIFY_TLS = os.environ.get("VERIFY_TLS", "true").lower() == "true"

DISCOVERY_PREFIX = os.environ.get("DISCOVERY_PREFIX", "homeassistant")
DEVICE_NAME = os.environ.get("DEVICE_NAME", "GroupAlarm Bridge")
DEVICE_ID = os.environ.get("DEVICE_ID", "groupalarm_bridge_1")

ORG_IDS = [int(x) for x in os.environ.get("ORG_IDS","").split(",") if x.strip().isdigit()]
PRIMARY_ORG_ID = int(os.environ.get("PRIMARY_ORG_ID","0"))

DEFAULT_TAG_ID = os.environ.get("DEFAULT_TAG_ID") or None
DEFAULT_EVENT_EXTERNAL_ID = os.environ.get("DEFAULT_EVENT_EXT_ID") or None

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

INGRESS_HOST = "0.0.0.0"
INGRESS_PORT = 8080

def auth_headers():
    return {"Personal-Access-Token": TOKEN}
