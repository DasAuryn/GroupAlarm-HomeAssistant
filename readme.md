# GroupAlarm App für Home Assistant 🚒

[![App Version](https://img.shields.io/badge/App%20Version-1.0.29-green?style=for-the-badge)](https://github.com/DasAuryn/GroupAlarm-HomeAssistant/releases/)
![Home Assistant Add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)
![HA Analytics](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fanalytics.home-assistant.io%2Faddons.json&query=%24%5B%271979cc44_groupalarm_homeassistant%27%5D.total&style=for-the-badge&label=Active%20Installations&color=red)
![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)

## Overview

Die **GroupAlarm App** bindet dein GroupAlarm-System in **Home Assistant** ein.  
Es bietet eine moderne Ingress-Oberfläche mit den Tabs **Alarme** (Standard) und **Quick-Actions**, zeigt Einsatzorte auf einer **Karte** (Leaflet), verwaltet **Orga-Avatare** und erstellt per **MQTT Discovery** passende Entitäten – ideal für Dashboards und Automationen.

## Installation

### App Store (empfohlen)

1. In Home Assistant **Einstellungen → Apps → App Store** öffnen.  
2. Über Menü (⋮) **Repositories** dieses Repo hinzufügen.  `https://github.com/DasAuryn/GroupAlarm-HomeAssistant.git`
3. **GroupAlarm App** installieren.  
4. In den **Einstellungen** die Konfiguration vornehmen (siehe unten).  
5. App **starten** und über **Ingress** öffnen.

> Hinweis: In älteren Home-Assistant-Versionen heißt dieser Bereich **Add-ons → Add-on Store**. Technisch ist die App weiterhin ein Supervisor-Add-on; Home Assistant zeigt diese Erweiterungen in aktuellen Versionen jedoch als **Apps** an.


### Manuell

Alternativ kann die App (z. B. via Docker) manuell deployt werden. Lade das Release von GitHub und starte mit passenden Umgebungsvariablen (siehe Konfiguration). Für Supervisor-/HAOS-Setups ist der App Store der einfachste Weg.

## Configuration

### Using UI

Die wichtigsten Optionen:

- `API_BASE_URL` – z. B. `https://app.groupalarm.com/api/v1`  
- `TOKEN` – dein GroupAlarm **Personal Access Token**  
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`  


#### Wie bekomme ich meinen API-Token?

1. In **GroupAlarm** einloggen.  
2. In den **Kontoeinstellungen** einen **Personal Access Token** erstellen/kopieren.  
3. In der App-Konfiguration `TOKEN` setzen und – falls nötig – `HEADER_NAME` an deine Instanz anpassen.

## Usage

Nach dem Start steht die Ingress-UI bereit:

- **Alarme (Standard-Tab)**  
  Zeigt aktuelle Alarme pro Orga inkl. **Adresse** und **Kartenmarker**.  
  Die Seite prüft alle paar Sekunden eine **Signatur** unter `/alarms.json` und lädt **nur bei Datenänderung** neu.

- **Quick-Actions**  
  Zeigt pro Orga Alarmbuttons.  
  

### Entities

Diese App stellt u. a. bereit:

- **Binary Sensor** je Orga: „**Alarm aktiv**“  
  Wird bei Eingang eines Alarms `on` und geht nach **5 Sekunden automatisch** auf `off` zurück (ideal für Flanken-Trigger).
  
## Help and Contribution

Probleme oder Wünsche?  
Erstelle ein **Issue** oder sende einen **Pull Request** – Beiträge sind willkommen!

## Disclaimer

Diese App ist **nicht** offiziell mit **GroupAlarm** verbunden.  
Die Nutzung erfolgt **auf eigenes Risiko**. Bitte beachte:

- Rechtmäßige Verarbeitung (insb. **DSGVO**),  
- Schutz sensibler personenbezogener Daten,  
- sichere Konfiguration deiner Home-Assistant-Instanz (starke Passwörter, TLS, Updates).

Je nach Setup können sensible Einsatz-/Personaldaten angezeigt werden. Sorge für eine geeignete Rechtsgrundlage und angemessene technische/organisatorische Maßnahmen.

--- 
