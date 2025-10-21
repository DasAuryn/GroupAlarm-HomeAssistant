GroupAlarm Bridge (Home Assistant Add-on)

Bindet GroupAlarm über die REST-API in Home Assistant ein.
Die Bridge erkennt automatisch deine Organisationen (per Personal-Access-Token), liest Quick Actions aus und stellt sie:

als schöne Ingress-UI mit Orga-Avataren & Buttons bereit und

(optional) als MQTT-Buttons via Home-Assistant-Discovery.

Ziel: Quick Actions aus GroupAlarm bequem aus Home Assistant auslösen – ohne manuelle Orga-IDs in der Config pflegen zu müssen.

Highlights

 Personal-Access-Token nutzen (Header: Personal-Access-Token)
(optional auch API Token → Header API-TOKEN, siehe Konfiguration)

Auto-Erkennung aller Organisationen über /organizations

Quick Actions je Orga aus /organization/{id}/quick-actions

Avatare aus /organizations im Ingress neben dem Orga-Namen

HA-Discovery (optional): erstellt MQTT-Buttons pro Quick Action

Auto-Cleanup: verlassene Orgas verschwinden (UI & MQTT)

TLS-Verifikation schaltbar

Wie es funktioniert

Beim Start ruft die Bridge /organizations auf, liest IDs, Namen, Avatare.

Für jede Orga werden Quick Actions geladen.

Die Bridge erzeugt einen UI-Cache (für Ingress) und optional MQTT-Discovery-Buttons.

Button-Klick (Ingress oder MQTT) →

resource-template: POST /alarm mit alarmResourceTemplateID

tag: POST /tags/{id}/trigger

Trittst du aus einer Orga aus, wird sie beim nächsten Refresh entfernt.

Voraussetzungen

Home Assistant OS/Supervised (Add-on Store verfügbar)

GroupAlarm Personal-Access-Token mit passenden Rechten

(optional) MQTT-Broker (z. B. Mosquitto Add-on), wenn du HA-Discovery-Buttons möchtest

Installation

Repository hinzufügen: Einstellungen → Add-ons → Add-on-Store → Repositories
https://github.com/DasAuryn/groupalarm-HomeAssistant

Add-on installieren: GroupAlarm HomeAssistant

Konfigurieren (siehe unten)

Starten und Ingress öffnen

Konfiguration

Beispiel (Add-on-Einstellungen):

api_base_url: "https://app.groupalarm.com/api/v1"
token: "DEIN_PERSONAL_ACCESS_TOKEN"
optional, steuert nur den Header-Namen:
token_type: "personal"   # "personal" → Personal-Access-Token (Default)
token_type: "api"        # "api"      → API-TOKEN
poll_interval_sec: 30

Ingress/Anzeige
device_name: "GroupAlarm Bridge"
device_id: "groupalarm_bridge_1"
verify_tls: true

MQTT (optional, nur wenn Discovery/Buttons gewünscht)
mqtt_host: "homeassistant"     # oder "core-mosquitto"
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
discovery_prefix: "homeassistant"


Wichtige Hinweise

Nur Token pflegen. Orga-IDs werden automatisch ermittelt.

token_type leer/„personal“ → Header Personal-Access-Token (empfohlen).
Bei „api“ nutzt die Bridge automatisch API-TOKEN.

verify_tls: true ist Standard. Bei Testumgebungen kannst du auf false stellen.

Ingress UI

Zeigt jede Orga mit Avatar und Quick-Action-Buttons.

Klick auf „Auslösen“ → Aktion wird sofort gegen GroupAlarm getriggert.

UI aktualisiert sich regelmäßig (standardmäßig alle 5 * poll_interval_sec).

Tipp: Wenn du gerade aus einer Orga ausgetreten bist und sie noch siehst, warte den nächsten Refresh ab oder starte das Add-on einmal neu.

MQTT-Discovery (optional)

Wenn MQTT konfiguriert ist, erzeugt die Bridge automatisch Button-Entities je Quick Action.

Topics (Standard-Prefix homeassistant):

Discovery-Config je Button:
homeassistant/button/<device_id>/org<ORG>_qa<QA>/config

Command-Topic zum Auslösen:
homeassistant/<device_id>/org/<ORG>/action/<QA>/set
Payload: PRESS

Die Bridge abonniert das Command-Topic und triggert die passende REST-Aktion.

Sicherheit

Der Token liegt in der Add-on-Konfiguration (Supervisor-Secret-Store).

Es werden keine personenbezogenen Daten gespeichert; nur Orga-Namen, Avatare, Quick-Action-Metadaten für die UI.
