# Changelog
## 1.0.33
- Bugfix: On updates or restarts, the binary sensors switched to on. This is fixed.

## 1.0.32

- Add MQTT sensors per organization for the latest alarm message, address, coordinates, event ID, event name, and alarm time.
- Combine latitude and longitude in one coordinate sensor, with both values available as attributes.
- Hide alarm detail sensors from dashboards by default while keeping them available for automations.
- Preserve complete texts as sensor attributes when they exceed Home Assistant's 255-character state limit.
- Keep the latest alarm details available independently of the five-second alarm pulse.
- Restore detail states through retained MQTT messages and preserve existing data when API requests fail.

## 1.0.31
- some bugfixes

## 1.0.30

feat(ui): redesign alarm and quick-action views

- add collapsible organization sections with persisted state
- show navigation counters for open, closed, and quick actions
- introduce compact responsive layout for desktop and mobile
- emphasize open alarms and defer map loading until expanded
- display GroupAlarm Material icons for quick actions
- derive dark-theme palettes from GroupAlarm action colors
- improve confirmation dialogs, keyboard support, and focus handling
- harden alarm, coordinate, color, and icon data validation

## 1.0.29

- Fix Home Assistant Ingress navigation for alarm tabs and Quick Actions.

## 1.0.28

- Add changelog metadata for Home Assistant app update dialogs.

## 1.0.27

- Add `armv7` support for Raspberry Pi HAOS installations.
- Add current Home Assistant Apps repository metadata.
- Split alarms into separate open and closed views.
- Add a confirmation dialog before triggering Quick Actions.

## 1.0.26

- Improve alarm event status handling and UI rendering.
