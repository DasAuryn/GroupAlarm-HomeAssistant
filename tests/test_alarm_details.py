import copy
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jinja2 import Environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run as bridge


class AlarmDetailsTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.publish.return_value = SimpleNamespace(rc=0)
        self.cache = {"by_org": {}}
        self.org_alarms = {}
        self.original_fetch = bridge.fetch_org_alarms
        self.save_cache = Mock(side_effect=self.store_cache)
        self.clock = Mock(return_value=1000)
        patches = (
            patch.object(bridge, "mqtt", self.client),
            patch.object(bridge, "have_mqtt", True),
            patch.object(bridge, "_last_alarm_details", {}),
            patch.object(bridge, "_last_alarm_published", {}),
            patch.object(bridge, "ALARM_RESET_SECONDS", 5),
            patch.object(bridge, "load_ui_cache", return_value={
                "names": {11: "Organisation A", 22: "Organisation B"}
            }),
            patch.object(bridge, "load_alarms_cache", side_effect=lambda: copy.deepcopy(self.cache)),
            patch.object(bridge, "save_alarms_cache", self.save_cache),
            patch.object(bridge, "fetch_org_alarms", side_effect=lambda org: copy.deepcopy(self.org_alarms.get(org, []))),
            patch.object(bridge, "fetch_open_event_ids", return_value={701, 702}),
            patch.object(bridge.time, "time", self.clock),
            patch.object(bridge, "print", create=True),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def store_cache(self, *, by_org):
        self.cache = {"by_org": copy.deepcopy(by_org)}

    def alarm(self, org=11, alarm_id=101, event_id=701):
        return {
            "id": alarm_id,
            "organizationID": org,
            "message": "Baum droht umzustürzen",
            "startDate": "2026-10-25T14:05:06+02:00",
            "event": {"id": event_id, "name": "Technische Hilfe"},
            "optionalContent": {
                "address": "Musterstraße 12, 12345 Musterstadt",
                "latitude": "52.52",
                "longitude": 13.405,
            },
        }

    def detail_topic(self, org):
        return f"{bridge.DISCOVERY}/{bridge.DEVICE_ID}/org/{org}/alarm/details"

    def publications(self, topic=None):
        messages = []
        for call in self.client.publish.call_args_list:
            published_topic, payload = call.args[:2]
            if topic is None or published_topic == topic:
                messages.append((published_topic, payload, call.kwargs))
        return messages

    def detail_payloads(self, org):
        return [json.loads(payload) for _, payload, _ in self.publications(self.detail_topic(org))]

    def test_payload_maps_event_id_separately_and_normalizes_timestamp(self):
        payload = bridge.alarm_details_payload(11, self.alarm())
        self.assertEqual(payload["organization_id"], 11)
        self.assertEqual(payload["alarm_id"], 101)
        self.assertEqual(payload["event_id"], 701)
        self.assertEqual(payload["event_name"], "Technische Hilfe")
        self.assertEqual(payload["address"], "Musterstraße 12, 12345 Musterstadt")
        self.assertEqual(payload["latitude"], 52.52)
        self.assertEqual(payload["longitude"], 13.405)
        self.assertEqual(payload["coordinates"], "52.52, 13.405")
        timestamp = datetime.fromisoformat(payload["start_date"].replace("Z", "+00:00"))
        self.assertEqual(timestamp.utcoffset(), timedelta(0))
        self.assertEqual((timestamp.hour, timestamp.minute, timestamp.second), (12, 5, 6))
        for fallback in ("eventID", "eventId"):
            alarm = self.alarm()
            alarm["event"] = None
            alarm[fallback] = "702"
            self.assertEqual(bridge.alarm_details_payload(11, alarm)["event_id"], 702)

    def test_missing_details_clear_values_without_inventing_an_event_id(self):
        payload = bridge.alarm_details_payload(11, None)
        self.assertEqual(payload["organization_id"], 11)
        self.assertIsNone(payload["alarm_id"])
        for field, _, _ in bridge.ALARM_DETAIL_SENSORS:
            self.assertIsNone(payload[field], field)
        alarm = self.alarm()
        alarm["event"] = {"name": ""}
        self.assertIsNone(bridge.alarm_details_payload(11, alarm)["event_id"])

    def test_invalid_coordinates_and_dates_are_unknown_but_zero_is_valid(self):
        for field, invalid in (
            ("latitude", "NaN"), ("latitude", float("inf")),
            ("latitude", True), ("latitude", 90.01),
            ("longitude", -180.01), ("longitude", {}),
        ):
            with self.subTest(field=field, invalid=invalid):
                alarm = self.alarm()
                alarm["optionalContent"][field] = invalid
                payload = bridge.alarm_details_payload(11, alarm)
                self.assertIsNone(payload[field])
                self.assertIsNone(payload["coordinates"])
        alarm = self.alarm()
        alarm["optionalContent"] = {"latitude": 0, "longitude": "0"}
        payload = bridge.alarm_details_payload(11, alarm)
        self.assertEqual((payload["latitude"], payload["longitude"]), (0.0, 0.0))
        self.assertEqual(payload["coordinates"], "0.0, 0.0")
        for invalid in ("2026-10-25T14:05:06", "invalid", None, 1792937106):
            with self.subTest(date=invalid):
                alarm["startDate"] = invalid
                self.assertIsNone(bridge.alarm_details_payload(11, alarm)["start_date"])
        for invalid in (None, True, False, 0, -1, "", "bad", 1.5):
            with self.subTest(alarm_id=invalid):
                self.assertIsNone(bridge._positive_alarm_id(invalid))
        self.assertEqual(bridge._positive_alarm_id("101"), 101)

    def test_discovery_is_separate_per_organisation_and_preserves_long_text(self):
        bridge.discovery_alarm_sensors(11, "Organisation A")
        bridge.discovery_alarm_sensors(22, "Organisation B")
        publications = self.publications()
        self.assertEqual(len(publications), 12)
        configs = {topic: json.loads(payload) for topic, payload, _ in publications}
        self.assertEqual(len({config["unique_id"] for config in configs.values()}), 12)
        self.assertTrue(all(config["visible_by_default"] is False for config in configs.values()))
        self.assertTrue(all(config.get("enabled_by_default", True) for config in configs.values()))
        self.assertTrue(all(options["retain"] for _, _, options in publications))
        environment = Environment()
        for org in (11, 22):
            for field in ("message", "address", "event_name"):
                with self.subTest(org=org, field=field):
                    topic = f"{bridge.DISCOVERY}/sensor/{bridge.DEVICE_ID}/org{org}_alarm_{field}/config"
                    config = configs[topic]
                    self.assertEqual(config["state_topic"], self.detail_topic(org))
                    self.assertEqual(config["json_attributes_topic"], self.detail_topic(org))
                    text = "Äöü Einsatzmeldung \"mit Details\"\n" * 20
                    values = {field: text}
                    state = environment.from_string(config["value_template"]).render(value_json=values)
                    attributes = environment.from_string(config["json_attributes_template"]).render(value_json=values)
                    self.assertEqual(state, text[:255])
                    self.assertEqual(json.loads(attributes)[field], text)
                    attributes = environment.from_string(config["json_attributes_template"]).render(value_json={field: None})
                    self.assertIsNone(json.loads(attributes)[field])
            timestamp_config = configs[f"{bridge.DISCOVERY}/sensor/{bridge.DEVICE_ID}/org{org}_alarm_start_date/config"]
            self.assertEqual(timestamp_config["device_class"], "timestamp")
            config = configs[f"{bridge.DISCOVERY}/sensor/{bridge.DEVICE_ID}/org{org}_alarm_coordinates/config"]
            values = bridge.alarm_details_payload(org, self.alarm(org=org))
            state = environment.from_string(config["value_template"]).render(value_json=values)
            attributes = json.loads(environment.from_string(config["json_attributes_template"]).render(value_json=values))
            self.assertEqual(state, "52.52, 13.405")
            self.assertEqual(attributes, {"latitude": 52.52, "longitude": 13.405})
            self.assertNotIn("unit_of_measurement", config)

    def test_latest_numeric_alarm_id_is_selected_independently_per_organisation(self):
        self.org_alarms = {
            11: [self.alarm(alarm_id="9"), self.alarm(alarm_id="10", event_id=702)],
            22: [self.alarm(org=22, alarm_id=7, event_id=703)],
        }
        bridge.alarm_poller_once([11, 22])
        self.assertEqual(self.detail_payloads(11)[-1]["alarm_id"], 10)
        self.assertEqual(self.detail_payloads(11)[-1]["event_id"], 702)
        self.assertEqual(self.detail_payloads(22)[-1]["alarm_id"], 7)
        self.assertEqual(self.detail_payloads(22)[-1]["event_id"], 703)
        self.assertTrue(all(options["retain"] for org in (11, 22)
                            for _, _, options in self.publications(self.detail_topic(org))))

    def test_detail_state_precedes_alarm_pulse_and_survives_reset(self):
        self.org_alarms[11] = [self.alarm()]
        bridge.alarm_poller_once([11])
        topics = [topic for topic, _, _ in self.publications()]
        alarm_topic = f"{bridge.DISCOVERY}/{bridge.DEVICE_ID}/org/11/alarm"
        self.assertLess(topics.index(self.detail_topic(11)), topics.index(alarm_topic))
        self.clock.return_value = 1006
        bridge.alarm_poller_once([11])
        self.assertFalse(json.loads(self.publications(alarm_topic)[-1][1])["active"])
        self.assertEqual(len(self.detail_payloads(11)), 1)
        self.assertEqual(bridge._last_alarm_details[11]["event_id"], 701)

    def test_changed_details_on_same_alarm_id_replace_old_optional_values(self):
        self.org_alarms[11] = [self.alarm()]
        bridge.alarm_poller_once([11])
        self.org_alarms[11][0]["message"] = "Aktualisierte Meldung"
        self.org_alarms[11][0]["optionalContent"] = None
        bridge.alarm_poller_once([11])
        payloads = self.detail_payloads(11)
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[-1]["alarm_id"], payloads[0]["alarm_id"])
        self.assertEqual(payloads[-1]["message"], "Aktualisierte Meldung")
        self.assertIsNone(payloads[-1]["address"])
        self.assertIsNone(payloads[-1]["latitude"])
        self.assertIsNone(payloads[-1]["longitude"])

    def test_failed_fetch_preserves_last_details_and_cached_alarm_list(self):
        self.org_alarms[11] = [self.alarm()]
        bridge.alarm_poller_once([11])
        previous_cache = copy.deepcopy(self.cache)
        self.org_alarms[11] = None
        bridge.alarm_poller_once([11])
        self.assertEqual(len(self.detail_payloads(11)), 1)
        self.assertEqual(self.cache, previous_cache)
        self.org_alarms[11] = []
        bridge.alarm_poller_once([11])
        self.assertIsNone(self.detail_payloads(11)[-1]["alarm_id"])
        self.assertIsNone(self.detail_payloads(11)[-1]["message"])
        self.assertEqual(self.cache["by_org"][11], [])

    def test_fetch_distinguishes_valid_empty_response_from_errors(self):
        with patch.object(bridge, "http", return_value={"alarms": []}):
            self.assertEqual(self.original_fetch(11), [])
        for invalid in (None, [], {}, {"alarms": {}}, {"alarms": [None]}):
            with self.subTest(response=invalid), patch.object(bridge, "http", return_value=invalid):
                self.assertIsNone(self.original_fetch(11))
        with patch.object(bridge, "http", side_effect=RuntimeError("synthetic API failure")):
            self.assertIsNone(self.original_fetch(11))

    def test_failed_mqtt_publish_is_retried_and_reconnect_republishes_unchanged_details(self):
        self.client.publish.return_value = SimpleNamespace(rc=4)
        bridge.publish_alarm_details(11, self.alarm())
        self.assertNotIn(11, bridge._last_alarm_details)
        self.client.publish.return_value = SimpleNamespace(rc=0)
        bridge.publish_alarm_details(11, self.alarm())
        bridge.publish_alarm_details(11, self.alarm())
        self.assertEqual(len(self.detail_payloads(11)), 2)
        bridge.on_mqtt_connect(self.client, None, {}, 5)
        bridge.publish_alarm_details(11, self.alarm())
        self.assertEqual(len(self.detail_payloads(11)), 2)
        bridge.on_mqtt_connect(self.client, None, {}, 0)
        bridge.publish_alarm_details(11, self.alarm())
        self.assertEqual(len(self.detail_payloads(11)), 3)

    def test_cleanup_removes_retained_detail_entities_and_their_state(self):
        bridge.publish_alarm_details(11, self.alarm())
        bridge.publish_alarm_details(22, self.alarm(org=22))
        self.client.publish.reset_mock()
        bridge.mqtt_cleanup_org(11, actions=[])
        published = {topic: (payload, options) for topic, payload, options in self.publications()}
        for field, _, _ in bridge.ALARM_DETAIL_SENSORS:
            topic = f"{bridge.DISCOVERY}/sensor/{bridge.DEVICE_ID}/org11_alarm_{field}/config"
            self.assertEqual(published[topic][0], b"")
            self.assertTrue(published[topic][1]["retain"])
        self.assertEqual(published[self.detail_topic(11)][0], b"")
        self.assertTrue(published[self.detail_topic(11)][1]["retain"])
        self.assertNotIn(11, bridge._last_alarm_details)
        self.assertIn(22, bridge._last_alarm_details)


if __name__ == "__main__":
    unittest.main()
