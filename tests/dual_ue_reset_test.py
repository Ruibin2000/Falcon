#!/usr/bin/env python3
"""Verify one-role reset and partial-failure behavior with an in-memory kernel."""

import contextlib
import copy
import importlib.util
import io
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("reset_ue_network", REPO / "scripts/dual_fr1/reset_ue_network.py")
RESET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESET)


class Kernel:
    def __init__(self):
        self.addresses = [
            {"ifname": "wwan0", "addr_info": [{"local": "10.45.0.3", "prefixlen": 29}, {"local": "10.45.1.9", "prefixlen": 24}]},
            {"ifname": "wwan1", "addr_info": [{"local": "10.46.0.2", "prefixlen": 30}]},
            {"ifname": "wifi", "addr_info": [{"local": "10.20.91.243", "prefixlen": 17}]},
        ]
        self.rules = [
            {"priority": 0, "src": "all", "table": "local"},
            {"priority": 10151, "src": "10.45.0.2", "dst": "10.45.0.1", "table": 151},
            {"priority": 10151, "src": "10.45.0.3", "dst": "10.45.0.1", "table": 151},
            {"priority": 10152, "src": "10.45.0.2", "dst": "10.45.0.1", "action": "unreachable"},
            {"priority": 10152, "src": "10.45.0.3", "dst": "10.45.0.1", "action": "unreachable"},
            {"priority": 10153, "src": "all", "dst": "10.45.0.1", "table": 151},
            {"priority": 10154, "src": "all", "dst": "10.45.0.1", "action": "unreachable"},
            {"priority": 12345, "src": "all", "dst": "10.45.0.8", "table": 151},
            {"priority": 12345, "src": "all", "dst": "10.46.0.8", "table": 152},
            {"priority": 10161, "src": "10.46.0.2", "dst": "10.46.0.1", "table": 152},
            {"priority": 10162, "src": "10.46.0.2", "dst": "10.46.0.1", "action": "unreachable"},
            {"priority": 32766, "src": "all", "table": "main"},
            {"priority": 32767, "src": "all", "table": "default"},
        ]
        self.routes = [
            {"table": 151, "dst": "10.45.0.1", "dev": "wwan0", "prefsrc": "10.45.0.3"},
            {"table": 151, "dst": "10.45.1.0/24", "dev": "wwan0", "prefsrc": "10.45.1.9"},
            {"table": 254, "dst": "10.45.0.1", "dev": "wwan0", "prefsrc": "10.45.0.2"},
            {"table": 254, "dst": "default", "dev": "wwan0"},
            {"table": 152, "dst": "10.46.0.1", "dev": "wwan1", "prefsrc": "10.46.0.2"},
            {"table": 254, "dst": "default", "dev": "wifi", "gateway": "10.20.0.1"},
            {"table": 254, "dst": "10.20.0.0/17", "dev": "wifi"},
        ]
        self.modems = {
            "/org/freedesktop/ModemManager1/Modem/77": (RESET.ROLES[1][0], "wwan0", "connected"),
            "/org/freedesktop/ModemManager1/Modem/88": (RESET.ROLES[2][0], "wwan1", "connected"),
        }
        self.bearers = {
            "/org/freedesktop/ModemManager1/Modem/77": {
                "/org/freedesktop/ModemManager1/Bearer/701": "yes",
                "/org/freedesktop/ModemManager1/Bearer/702": "no",
            },
            "/org/freedesktop/ModemManager1/Modem/88": {
                "/org/freedesktop/ModemManager1/Bearer/801": "yes",
                "/org/freedesktop/ModemManager1/Bearer/802": "no",
            },
        }
        self.links = {"wwan0": (1400, "UP"), "wwan1": (1400, "UP"), "wifi": (1500, "UP")}
        self.changes = []
        self.fail = None
        self.mm_unavailable = False
        self.addr_reads = 0
        self.recreate_address = False
        self.recreate_after_addr_read = 2
        self.aliases = {"main": 254, "local": 255, "default": 253, "falcon151": 151}

    def number(self, value):
        return int(value) if str(value).isdigit() else self.aliases.get(value)

    def read(self, *command):
        if command == ("mmcli", "-L"):
            if self.mm_unavailable:
                raise subprocess.CalledProcessError(1, command, stderr="No ModemManager service")
            return "\n".join(self.modems)
        if command[:2] == ("mmcli", "-m"):
            imei, device, state = self.modems[command[2]]
            return (f"modem.generic.equipment-identifier : {imei}\n"
                    f"modem.generic.ports.value[1] : {device} (net)\n"
                    f"modem.generic.state : {state}\n" + "\n".join(
                        f"modem.generic.bearers.value[{index}] : {path}" for index, path in
                        enumerate(self.bearers.get(command[2], {}), 1)))
        if command[:2] == ("mmcli", "-b"):
            states = [owned[command[2]] for owned in self.bearers.values() if command[2] in owned]
            assert len(states) == 1
            return f"bearer.status.connected : {states[0]}\n"
        assert command[:3] == ("ip", "-j", "-4"), command
        args = command[3:]
        if args == ("addr", "show"):
            self.addr_reads += 1
            if self.recreate_address and self.addr_reads == self.recreate_after_addr_read:
                self.addresses[0]["addr_info"].append({"local": "10.45.9.9", "prefixlen": 30})
            return json.dumps(self.addresses)
        if args == ("rule", "show"):
            return json.dumps(self.rules)
        if args[:3] == ("route", "show", "table"):
            return json.dumps([route for route in self.routes if self.number(route["table"]) == self.number(args[3])])
        raise AssertionError(command)

    def change(self, *command):
        self.changes.append(command)
        if self.fail and tuple(command[:len(self.fail)]) == self.fail:
            raise subprocess.CalledProcessError(1, command)
        if command[0] == "mmcli":
            path, option = command[2:]
            imei, device, _ = self.modems[path]
            if option == "--simple-disconnect":
                self.modems[path] = (imei, device, "registered")
                self.bearers[path] = {bearer: "no" for bearer in self.bearers.get(path, {})}
            elif option.startswith("--delete-bearer="):
                del self.bearers[path][option.split("=", 1)[1]]
            elif option == "--disable":
                self.modems[path] = (imei, device, "disabled")
            else:
                raise AssertionError(command)
        elif command[:4] == ("ip", "-4", "route", "flush"):
            table = self.number(command[5])
            device = command[command.index("dev") + 1] if "dev" in command else None
            pool = ipaddress.IPv4Network(command[command.index("to") + 1]) if "to" in command else None
            def removed(route):
                return (self.number(route["table"]) == table and (device is None or route.get("dev") == device)
                        and (pool is None or (route.get("dst") != "default"
                             and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool))))
            self.routes = [route for route in self.routes if not removed(route)]
        elif command[:4] == ("ip", "-4", "addr", "flush"):
            device, pool = command[5], ipaddress.IPv4Network(command[7])
            for entry in self.addresses:
                if entry["ifname"] == device:
                    entry["addr_info"] = [info for info in entry["addr_info"] if ipaddress.IPv4Address(info["local"]) not in pool]
        elif command[:3] == ("ip", "link", "set"):
            self.links[command[4]] = (int(command[6]), command[7].upper())
        elif command[:4] == ("ip", "-4", "rule", "del"):
            priority = int(command[5])
            table = self.number(command[7]) if "lookup" in command else None
            matches = [rule for rule in self.rules if rule["priority"] == priority and
                       (table is None or self.number(rule.get("table")) == table)]
            assert matches, command
            self.rules.remove(matches[0])
        else:
            raise AssertionError(command)

    def survivor(self, ue):
        octet, table, priorities = (46, 152, (10161, 10162)) if ue == 1 else (45, 151, (10151, 10152, 10153, 10154))
        devices = {entry["ifname"] for entry in self.addresses if any(
            info["local"].startswith((f"10.{octet}.", "10.20.")) for info in entry["addr_info"])}
        return copy.deepcopy(([entry for entry in self.addresses if entry["ifname"] in devices],
            [rule for rule in self.rules if self.number(rule.get("table")) == table or rule["priority"] in priorities
             or rule["priority"] in (0, 32766, 32767)],
            [route for route in self.routes if self.number(route["table"]) == table or route.get("dev") == "wifi"],
            {device: self.links[device] for device in devices}))


class ResetTest(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel()
        for name in ("read", "change", "table_aliases"):
            replacement = getattr(self.kernel, name) if name != "table_aliases" else lambda: self.kernel.aliases
            mock = patch.object(RESET, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        self.stdout = io.StringIO()
        capture = contextlib.redirect_stdout(self.stdout)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def assert_clean(self, ue):
        _, pool, _, table, priorities = RESET.ROLES[ue]
        self.assertFalse(any(self.kernel.number(rule.get("table")) == table or rule["priority"] in priorities for rule in self.kernel.rules))
        self.assertFalse(any(self.kernel.number(route["table"]) == table for route in self.kernel.routes))
        self.assertFalse(any(ipaddress.IPv4Address(info["local"]) in ipaddress.IPv4Network(pool)
                             for device in self.kernel.addresses for info in device["addr_info"]))
        self.assertIn(f"UE{ue} reset complete", self.stdout.getvalue())

    def test_ue1_clears_all_allocations_duplicates_legacy_routes_and_preserves_survivor(self):
        survivor = self.kernel.survivor(1)
        RESET.reset(1)
        self.assert_clean(1)
        self.assertEqual(self.kernel.survivor(1), survivor)
        self.assertEqual(self.kernel.links["wwan0"], (1500, "DOWN"))
        self.assertFalse(any(route.get("dev") == "wwan0" for route in self.kernel.routes))

    def test_ue2_clears_its_role_without_changing_ue1(self):
        survivor = self.kernel.survivor(2)
        RESET.reset(2)
        self.assert_clean(2)
        self.assertEqual(self.kernel.survivor(2), survivor)

    def test_legacy_role_route_on_other_wwan_does_not_flush_its_default_or_addresses(self):
        self.kernel.routes.append({"table": 254, "dst": "10.45.9.0/24", "dev": "wwan1"})
        self.kernel.routes.append({"table": 254, "dst": "default", "dev": "wwan1"})
        other_addresses = copy.deepcopy(self.kernel.addresses[1])
        RESET.reset(1)
        self.assert_clean(1)
        self.assertEqual(self.kernel.addresses[1], other_addresses)
        self.assertIn({"table": 254, "dst": "default", "dev": "wwan1"}, self.kernel.routes)
        self.assertNotIn({"table": 254, "dst": "10.45.9.0/24", "dev": "wwan1"}, self.kernel.routes)
        self.assertEqual(self.kernel.links["wwan1"], (1400, "UP"))

    def test_changed_modem_indices_and_network_name_are_discovered_by_imei(self):
        self.kernel.addresses[0]["ifname"] = "wwan7"
        for route in self.kernel.routes:
            if route.get("dev") == "wwan0":
                route["dev"] = "wwan7"
        self.kernel.modems["/org/freedesktop/ModemManager1/Modem/900"] = self.kernel.modems.pop("/org/freedesktop/ModemManager1/Modem/77")
        self.kernel.modems["/org/freedesktop/ModemManager1/Modem/900"] = (RESET.ROLES[1][0], "wwan7", "connected")
        RESET.reset(1)
        self.assert_clean(1)
        self.assertEqual(self.kernel.links["wwan7"], (1500, "DOWN"))

    def test_unmanaged_orphan_wwan_addresses_need_no_old_session_record(self):
        del self.kernel.modems["/org/freedesktop/ModemManager1/Modem/77"]
        RESET.reset(1)
        self.assert_clean(1)

    def test_no_modem_or_address_still_clears_stale_rules_and_table(self):
        del self.kernel.modems["/org/freedesktop/ModemManager1/Modem/77"]
        self.kernel.addresses[0]["addr_info"] = []
        RESET.reset(1)
        self.assert_clean(1)

    def test_missing_current_interface_does_not_block_rule_cleanup(self):
        self.kernel.addresses = self.kernel.addresses[1:]
        RESET.reset(1)
        self.assert_clean(1)

    def test_missing_manager_without_role_addresses_allows_route_cleanup(self):
        self.kernel.mm_unavailable = True
        self.kernel.addresses[0]["addr_info"] = []
        RESET.reset(1)
        self.assert_clean(1)

    def test_missing_manager_with_live_addresses_refuses_before_mutation(self):
        self.kernel.mm_unavailable = True
        with self.assertRaises(ValueError):
            RESET.reset(1)
        self.assertEqual(self.kernel.changes, [])

    def test_named_private_table_alias_is_removed(self):
        for item in self.kernel.rules + self.kernel.routes:
            if item.get("table") == 151:
                item["table"] = "falcon151"
        RESET.reset(1)
        self.assert_clean(1)

    def test_repeat_reset_is_idempotent(self):
        RESET.reset(1)
        survivor = self.kernel.survivor(1)
        RESET.reset(1)
        self.assert_clean(1)
        self.assertEqual(self.kernel.survivor(1), survivor)

    def test_address_failure_keeps_guards_and_never_reports_complete(self):
        self.kernel.fail = ("ip", "-4", "addr", "flush")
        with self.assertRaises(subprocess.CalledProcessError):
            RESET.reset(1)
        self.assertTrue(any(rule["priority"] == 10154 for rule in self.kernel.rules))
        self.assertNotIn("reset complete", self.stdout.getvalue())

    def test_recreated_address_keeps_guards_and_never_reports_complete(self):
        self.kernel.recreate_address = True
        with self.assertRaisesRegex(ValueError, "address remains"):
            RESET.reset(1)
        self.assertTrue(any(rule["priority"] == 10154 for rule in self.kernel.rules))
        self.assertNotIn("reset complete", self.stdout.getvalue())

    def test_address_recreated_during_policy_cleanup_is_detected_by_final_check(self):
        self.kernel.recreate_address = True
        self.kernel.recreate_after_addr_read = 3
        with self.assertRaisesRegex(ValueError, "incomplete"):
            RESET.reset(1)
        self.assertNotIn("reset complete", self.stdout.getvalue())

    def test_misassigned_other_modem_is_preserved(self):
        path = "/org/freedesktop/ModemManager1/Modem/77"
        self.kernel.modems[path] = (RESET.ROLES[2][0], "wwan0", "connected")
        with self.assertRaisesRegex(ValueError, "another modem"):
            RESET.reset(1)
        self.assertEqual(self.kernel.changes, [])

    def test_foreign_address_on_selected_wwan_refuses_before_changes(self):
        self.kernel.addresses[0]["addr_info"].append({"local": "192.168.1.2", "prefixlen": 24})
        with self.assertRaisesRegex(ValueError, "outside"):
            RESET.reset(1)
        self.assertEqual(self.kernel.changes, [])

    def test_server_host_cannot_be_reset_as_laptop(self):
        self.kernel.addresses.append({"ifname": "ogstun", "addr_info": [{"local": "10.45.0.1", "prefixlen": 16}]})
        with self.assertRaisesRegex(ValueError, "Spark"):
            RESET.reset(1)
        self.assertEqual(self.kernel.changes, [])

    def test_dry_run_changes_nothing(self):
        RESET.reset(1, dry_run=True, disconnect=True)
        self.assertEqual(self.kernel.changes, [])
        self.assertIn("would remove rule", self.stdout.getvalue())

    def test_final_cleanup_disconnects_only_current_imei(self):
        RESET.reset(1, disconnect=True)
        self.assert_clean(1)
        self.assertEqual(self.kernel.modems["/org/freedesktop/ModemManager1/Modem/77"][2], "registered")
        self.assertEqual(self.kernel.modems["/org/freedesktop/ModemManager1/Modem/88"][2], "connected")

    def test_built_in_priority_conflict_is_not_deleted(self):
        self.kernel.rules[0]["table"] = 151
        with self.assertRaisesRegex(ValueError, "built-in"):
            RESET.reset(1)
        self.assertEqual(self.kernel.changes, [])

    def test_shutdown_ue1_disconnects_deletes_all_bearers_and_disables_only_ue1(self):
        path = "/org/freedesktop/ModemManager1/Modem/77"
        other = "/org/freedesktop/ModemManager1/Modem/88"
        survivor = self.kernel.survivor(1)
        other_bearers = copy.deepcopy(self.kernel.bearers[other])
        RESET.reset(1, shutdown=True)
        self.assert_clean(1)
        self.assertEqual(self.kernel.bearers[path], {})
        self.assertEqual(self.kernel.modems[path][2], "disabled")
        self.assertEqual(self.kernel.modems[other][2], "connected")
        self.assertEqual(self.kernel.bearers[other], other_bearers)
        self.assertEqual(self.kernel.survivor(1), survivor)
        modem_changes = [command[-1] for command in self.kernel.changes if command[0] == "mmcli"]
        self.assertEqual(modem_changes, ["--simple-disconnect",
            "--delete-bearer=/org/freedesktop/ModemManager1/Bearer/701",
            "--delete-bearer=/org/freedesktop/ModemManager1/Bearer/702", "--disable"])
        self.assertIn("UE1 shutdown complete", self.stdout.getvalue())

    def test_shutdown_ue2_preserves_ue1_addresses_rules_modem_and_bearers(self):
        path = "/org/freedesktop/ModemManager1/Modem/88"
        other = "/org/freedesktop/ModemManager1/Modem/77"
        survivor = self.kernel.survivor(2)
        other_bearers = copy.deepcopy(self.kernel.bearers[other])
        RESET.reset(2, shutdown=True)
        self.assert_clean(2)
        self.assertEqual(self.kernel.bearers[path], {})
        self.assertEqual(self.kernel.modems[path][2], "disabled")
        self.assertEqual(self.kernel.modems[other][2], "connected")
        self.assertEqual(self.kernel.bearers[other], other_bearers)
        self.assertEqual(self.kernel.survivor(2), survivor)

    def test_shutdown_dry_run_lists_disconnect_bearer_deletion_and_disable_without_changes(self):
        RESET.reset(1, dry_run=True, shutdown=True)
        self.assertEqual(self.kernel.changes, [])
        self.assertIn("--simple-disconnect", self.stdout.getvalue())
        self.assertIn("--delete-bearer=", self.stdout.getvalue())
        self.assertIn("--disable", self.stdout.getvalue())

    def test_shutdown_of_disabled_modem_with_no_bearers_is_idempotent(self):
        RESET.reset(1, shutdown=True)
        self.kernel.changes.clear()
        RESET.reset(1, shutdown=True)
        self.assert_clean(1)
        self.assertEqual([command for command in self.kernel.changes if command[0] == "mmcli"], [])

    def test_shutdown_requires_current_modem_before_mutations(self):
        del self.kernel.modems["/org/freedesktop/ModemManager1/Modem/77"]
        with self.assertRaisesRegex(ValueError, "modem is absent"):
            RESET.reset(1, shutdown=True)
        self.assertEqual(self.kernel.changes, [])

    def test_failed_bearer_deletion_never_disables_or_claims_shutdown(self):
        path = "/org/freedesktop/ModemManager1/Modem/77"
        self.kernel.fail = ("mmcli", "-m", path, "--delete-bearer=/org/freedesktop/ModemManager1/Bearer/701")
        with self.assertRaises(subprocess.CalledProcessError):
            RESET.reset(1, shutdown=True)
        self.assertFalse(any(command[-1] == "--disable" for command in self.kernel.changes))
        self.assertNotIn("shutdown complete", self.stdout.getvalue())

    def test_failed_modem_disable_does_not_claim_shutdown(self):
        self.kernel.fail = ("mmcli", "-m", "/org/freedesktop/ModemManager1/Modem/77", "--disable")
        with self.assertRaises(subprocess.CalledProcessError):
            RESET.reset(1, shutdown=True)
        self.assertNotIn("shutdown complete", self.stdout.getvalue())

    def test_reconnected_bearer_stops_shutdown_before_deletion(self):
        original = self.kernel.change
        def reconnect(*command):
            original(*command)
            if command[-1] == "--simple-disconnect":
                self.kernel.bearers[command[2]]["/org/freedesktop/ModemManager1/Bearer/701"] = "yes"
        with patch.object(RESET, "change", reconnect):
            with self.assertRaisesRegex(ValueError, "remains connected or was reconnected"):
                RESET.reset(1, shutdown=True)
        self.assertFalse(any(command[-1].startswith("--delete-bearer=") or command[-1] == "--disable"
                             for command in self.kernel.changes))

    def test_identity_change_during_bearer_deletion_stops_before_touching_replacement(self):
        original = self.kernel.change
        def replace(*command):
            original(*command)
            if command[-1].startswith("--delete-bearer="):
                _, device, state = self.kernel.modems[command[2]]
                self.kernel.modems[command[2]] = (RESET.ROLES[2][0], device, state)
        with patch.object(RESET, "change", replace):
            with self.assertRaisesRegex(ValueError, "identity changed"):
                RESET.reset(1, shutdown=True)
        self.assertEqual(sum(command[-1].startswith("--delete-bearer=") for command in self.kernel.changes), 1)
        self.assertFalse(any(command[-1] == "--disable" for command in self.kernel.changes))

    def test_bearer_recreated_during_disable_is_reported_as_incomplete(self):
        original = self.kernel.change
        def recreate(*command):
            original(*command)
            if command[-1] == "--disable":
                self.kernel.bearers[command[2]]["/org/freedesktop/ModemManager1/Bearer/999"] = "no"
        with patch.object(RESET, "change", recreate):
            with self.assertRaisesRegex(ValueError, "shutdown is incomplete"):
                RESET.reset(1, shutdown=True)
        self.assertNotIn("shutdown complete", self.stdout.getvalue())

    def test_disconnect_only_keeps_bearer_objects_and_modem_enabled(self):
        path = "/org/freedesktop/ModemManager1/Modem/77"
        paths = set(self.kernel.bearers[path])
        RESET.reset(1, disconnect=True)
        self.assertEqual(set(self.kernel.bearers[path]), paths)
        self.assertEqual(set(self.kernel.bearers[path].values()), {"no"})
        self.assertEqual(self.kernel.modems[path][2], "registered")

    def test_host_address_recreated_during_disable_does_not_report_shutdown_complete(self):
        original = self.kernel.change
        def recreate(*command):
            original(*command)
            if command[-1] == "--disable":
                self.kernel.addresses[0]["addr_info"].append({"local": "10.45.0.9", "prefixlen": 30})
        with patch.object(RESET, "change", recreate):
            with self.assertRaisesRegex(ValueError, "reset is incomplete"):
                RESET.reset(1, shutdown=True)
        self.assertNotIn("shutdown complete", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
