#!/usr/bin/env bash
set -Eeuo pipefail

API_BASE_URL=$(jq -r '.api_base_url // "https://app.groupalarm.com/api/v1"' /data/options.json)
TOKEN_TYPE=$(jq -r '.token_type // "personal"' /data/options.json)  
TOKEN=$(jq -r '.token // ""' /data/options.json)

USER_ID_RAW=$(jq -r '(.user_id // 0)' /data/options.json || echo 0)
POLL_INTERVAL=$(jq -r '(.poll_interval_sec // 30)' /data/options.json)
DISCOVERY_PREFIX=$(jq -r '(.discovery_prefix // "homeassistant")' /data/options.json)
DEVICE_NAME=$(jq -r '(.device_name // "GroupAlarm Bridge")' /data/options.json)
DEVICE_ID=$(jq -r '(.device_id // "groupalarm_bridge_1")' /data/options.json)
VERIFY_TLS=$(jq -r '(.verify_tls // true)' /data/options.json)

DEFAULT_TAG_ID=$(jq -r '(.default_tag_id // empty)' /data/options.json)
DEFAULT_EVENT_EXT_ID=$(jq -r '(.default_event_external_id // empty)' /data/options.json)

if ! [[ "$USER_ID_RAW" =~ ^[0-9]+$ ]]; then
  echo "[GA][WARN] options.user_id ist nicht numerisch ('${USER_ID_RAW}'); setze 0."
  USER_ID=0
else
  USER_ID=$USER_ID_RAW
fi

CURL_OPTS=()
if [ "${VERIFY_TLS}" != "true" ]; then
  CURL_OPTS+=("--insecure")
fi

HEADER_NAME="Personal-Access-Token"
if [ "$TOKEN_TYPE" = "api" ]; then
  HEADER_NAME="API-TOKEN"
fi

echo "[GA] GET ${API_BASE_URL%/}/organizations …"
HTTP_CODE=$(curl -sS -w "%{http_code}" -o /data/organizations.json \
  -H "$HEADER_NAME: $TOKEN" "${CURL_OPTS[@]}" \
  "${API_BASE_URL%/}/organizations") || { echo "[GA][ERR] curl fehlgeschlagen"; exit 1; }

PREVIEW=$(head -c 300 /data/organizations.json | tr '\n' ' ')
SIZE=$(wc -c < /data/organizations.json | tr -d ' ')
echo "[GA] HTTP $HTTP_CODE, bytes: $SIZE, first bytes: ${PREVIEW}"

if ! jq -e 'type=="array"' /data/organizations.json >/dev/null 2>&1; then
  echo "[GA][ERR] /organizations ist KEIN Array. Inhalt unten:"
  cat /data/organizations.json
  exit 1
fi

PRIMARY_ORG_ID=$(
  jq -r --argjson uid "${USER_ID:-0}" '
    if type=="array" then
      # 1) Root-Orgs, bei denen user_id in ownerIDs vorkommt
      ( [ .[] | select((.parentID//0)==0 and ((.ownerIDs//[]) | any(. == $uid))) ] | if length>0 then .[0].id else empty end ) //
      # 2) irgendeine Root-Orga
      ( [ .[] | select((.parentID//0)==0) ] | if length>0 then .[0].id else empty end ) //
      # 3) erste Orga
      ( if length>0 then .[0].id else 0 end )
    else 0 end
  ' /data/organizations.json
)

ORG_IDS_CSV=$(
  jq -r '
    if type=="array" then
      (map(.id) | join(","))
    else
      ""
    end
  ' /data/organizations.json
)

if [ -z "$ORG_IDS_CSV" ]; then
  echo "[GA][ERR] Konnte keine Orga-IDs aus /organizations extrahieren."
  exit 1
fi

echo "[GA] Gefundene Orgs: ${ORG_IDS_CSV} (Primär: ${PRIMARY_ORG_ID})"


export API_BASE_URL TOKEN TOKEN_TYPE HEADER_NAME
export USER_ID PRIMARY_ORG_ID ORG_IDS="${ORG_IDS_CSV}"
export POLL_INTERVAL DISCOVERY_PREFIX DEVICE_NAME DEVICE_ID VERIFY_TLS
export DEFAULT_TAG_ID="${DEFAULT_TAG_ID:-}" DEFAULT_EVENT_EXT_ID="${DEFAULT_EVENT_EXT_ID:-}"
export MQTT_HOST="${MQTT_HOST:-$(jq -r '(.mqtt_host // empty)' /data/options.json)}"
export MQTT_PORT="${MQTT_PORT:-$(jq -r '(.mqtt_port // 1883)' /data/options.json)}"
export MQTT_USERNAME="${MQTT_USERNAME:-$(jq -r '(.mqtt_username // empty)' /data/options.json)}"
export MQTT_PASSWORD="${MQTT_PASSWORD:-$(jq -r '(.mqtt_password // empty)' /data/options.json)}"
gunicorn -w 2 -b 0.0.0.0:8099 web:app &

exec python3 -u /run.py