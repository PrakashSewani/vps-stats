"""Test the statistics exporter; run with ``python3 tests/test_exporter.py``."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES = TESTS_DIR / "fixtures"
MODULE_PATH = TESTS_DIR.parent / "exporter" / "stats.py"
SPEC = importlib.util.spec_from_file_location("vps_stats_exporter", str(MODULE_PATH))
assert SPEC is not None and SPEC.loader is not None
stats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stats)


class FakeResult:
    """Small subprocess result stand-in used to keep tests off the network."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_proc(directory: Path, stat_fixture: str = "proc_stat_a.txt") -> None:
    shutil.copyfile(str(FIXTURES / stat_fixture), str(directory / "stat"))
    shutil.copyfile(str(FIXTURES / "proc_meminfo.txt"), str(directory / "meminfo"))
    shutil.copyfile(str(FIXTURES / "proc_loadavg.txt"), str(directory / "loadavg"))
    (directory / "uptime").write_text("130000.00 0.00\n", encoding="utf-8")


def successful_mac_runner(*args: Any, **kwargs: Any) -> FakeResult:
    return FakeResult(0, fixture_text("mac_probe_raw.txt"), "")


class ExporterTests(unittest.TestCase):
    def test_cpu_delta_uses_recorded_pair(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            shutil.copyfile(str(FIXTURES / "proc_stat_a.txt"), str(Path(first) / "stat"))
            shutil.copyfile(str(FIXTURES / "proc_stat_b.txt"), str(Path(second) / "stat"))
            pair_a = stats.read_cpu_times(first)
            pair_b = stats.read_cpu_times(second)
        self.assertEqual((13103469, 12440338), pair_a)
        self.assertEqual((13105056, 12441790), pair_b)
        # The two snapshots are 16 s apart, so the caller declares a 16 s window and the delta
        # is the right number for it.
        delta = stats.cpu_busy_pct(pair_b, pair_a, 16)
        self.assertEqual(8.5, delta)
        # With no window to declare, the delta is not a measurement: lifetime average.
        self.assertNotEqual(stats.cpu_busy_pct(pair_b), delta)

    def test_short_delta_window_reports_the_lifetime_average(self) -> None:
        # A tick that outruns its interval makes systemd fire the next one immediately, so two
        # samples land a fraction of a second apart and the sampler's own interpreter start-up
        # is most of the window. Measured on this box while it was 5.6% busy: four back-to-back
        # ticks reported 100.0 / 100.0 / 91.7 / 100.0. The pair below is the recorded snapshot
        # with ~0.12 s of ticks (12 at ~99/s) removed, which reproduces that shape.
        pair_b = (13105056, 12441790)
        near = (pair_b[0] - 12, pair_b[1] - 1)
        self.assertEqual(91.7, stats.cpu_busy_pct(pair_b, near, 16))
        self.assertEqual(5.1, stats.cpu_busy_pct(pair_b, near, 0.12))
        # Refused, so the answer is exactly the no-pair answer.
        self.assertEqual(stats.cpu_busy_pct(pair_b), stats.cpu_busy_pct(pair_b, near, 0.12))
        self.assertEqual(stats.cpu_busy_pct(pair_b), stats.cpu_busy_pct(pair_b, near, None))
        self.assertEqual(stats.cpu_busy_pct(pair_b), stats.cpu_busy_pct(pair_b, near, 4.9))

    def test_a_bunched_tick_uses_the_lifetime_average(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            state = root / "state"
            proc.mkdir()
            make_proc(proc, "proc_stat_a.txt")
            stats.run_tick(str(state), str(proc), no_mac=True, now=1000)
            shutil.copyfile(str(FIXTURES / "proc_stat_b.txt"), str(proc / "stat"))
            bunched = stats.run_tick(str(state), str(proc), no_mac=True, now=1001)
            # One second is below the floor, so the recorded pair is not trusted over that
            # window (the measured bunching window was 0.12 s; same code path).
            self.assertEqual(
                stats.cpu_busy_pct(stats.read_cpu_times(str(proc))),
                bunched["hosts"]["vps"]["cpu"]["busy_pct"],
            )
            stored = json.loads((state / "prev.json").read_text(encoding="utf-8"))
            # Without the tick time in prev.json the next tick cannot tell a 15 s window from a
            # 0.1 s one, so the state file has to carry it.
            self.assertEqual(1001, stored["at"])
            self.assertIn("total", stored)
            self.assertIn("idle", stored)

    def test_previous_file_without_a_tick_time_falls_back(self) -> None:
        # A prev.json written before the window was recorded cannot measure one, so the first
        # tick after an upgrade reports the lifetime average. Self-healing: the next tick writes
        # a complete record and the delta resumes.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            state = root / "state"
            proc.mkdir()
            state.mkdir()
            make_proc(proc, "proc_stat_a.txt")
            pair_b = (13105056, 12441790)
            stats.write_json_atomic(state / "prev.json", {"total": pair_b[0], "idle": pair_b[1]})
            shutil.copyfile(str(FIXTURES / "proc_stat_b.txt"), str(proc / "stat"))
            tick = stats.run_tick(str(state), str(proc), no_mac=True, now=1016)
            self.assertEqual(
                stats.cpu_busy_pct(pair_b), tick["hosts"]["vps"]["cpu"]["busy_pct"]
            )

    def test_first_run_falls_back_then_second_run_uses_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            state = root / "state"
            proc.mkdir()
            make_proc(proc, "proc_stat_a.txt")
            first = stats.run_tick(str(state), str(proc), no_mac=True, now=1000)
            first_cpu = first["hosts"]["vps"]["cpu"]["busy_pct"]
            self.assertGreaterEqual(first_cpu, 0)
            self.assertLessEqual(first_cpu, 100)
            shutil.copyfile(str(FIXTURES / "proc_stat_b.txt"), str(proc / "stat"))
            second = stats.run_tick(str(state), str(proc), no_mac=True, now=1016)
            self.assertEqual(8.5, second["hosts"]["vps"]["cpu"]["busy_pct"])

    def test_state_directory_round_trip_adds_one_point_per_series(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc_a = root / "proc-a"
            proc_b = root / "proc-b"
            state = root / "state"
            proc_a.mkdir()
            proc_b.mkdir()
            make_proc(proc_a, "proc_stat_a.txt")
            make_proc(proc_b, "proc_stat_b.txt")
            first = stats.run_tick(
                str(state),
                str(proc_a),
                force_mac=True,
                now=1792164161,
                mac_runner=successful_mac_runner,
            )
            for name in ("stats.json", "history.json", "prev.json"):
                with (state / name).open("r", encoding="utf-8") as handle:
                    self.assertIsInstance(json.load(handle), dict)
            self.assertEqual(1, first["schema"])
            second = stats.run_tick(
                str(state),
                str(proc_b),
                force_mac=True,
                now=1792164177,
                mac_runner=successful_mac_runner,
            )
            self.assertEqual(2, len(second["history"]["vps"]["t"]))
            self.assertEqual(2, len(second["history"]["mac"]["t"]))
            self.assertNotEqual(
                first["hosts"]["vps"]["cpu"]["busy_pct"],
                second["hosts"]["vps"]["cpu"]["busy_pct"],
            )

    def test_memory_and_swap_maths_from_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "meminfo"
            shutil.copyfile(str(FIXTURES / "proc_meminfo.txt"), str(target))
            values = stats.read_meminfo(temporary)
        memory, swap = stats.memory_stats(values)
        self.assertEqual(3.77, memory["total_gb"])
        self.assertEqual(1.45, memory["used_gb"])
        self.assertAlmostEqual(38.5, memory["used_pct"], delta=0.05)
        self.assertEqual(2.0, swap["total_gb"])

    def test_ring_is_bounded_oldest_first(self) -> None:
        history = stats.new_history(capacity=240)
        for index in range(300):
            stats.push_history(history, "vps", index, float(index), None)
        self.assertEqual(240, len(history["vps"]["t"]))
        self.assertEqual(60, history["vps"]["t"][0])
        self.assertEqual(299, history["vps"]["t"][-1])

    def test_mac_status_array_stays_parallel_after_mixed_pushes(self) -> None:
        history = stats.new_history(capacity=3)
        points = (
            (1, None, None, "online"),
            (2, 20.0, None, "online"),
            (3, None, 50.0, "online"),
            (4, 10.0, 40.0, "online"),
        )
        for timestamp, cpu, memory, status in points:
            stats.push_history(history, "mac", timestamp, cpu, memory, status=status)
        mac = history["mac"]
        self.assertEqual(3, len(mac["t"]))
        self.assertEqual(len(mac["t"]), len(mac["cpu_pct"]))
        self.assertEqual(len(mac["t"]), len(mac["mem_pct"]))
        self.assertEqual(len(mac["t"]), len(mac["status"]))
        stats.assert_history(history)

    def test_atomic_write_leaves_only_valid_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "value.json"
            stats.write_json_atomic(target, {"wide": "Prakash’s", "number": 3})
            with target.open("r", encoding="utf-8") as handle:
                self.assertEqual({"wide": "Prakash’s", "number": 3}, json.load(handle))
            self.assertEqual(["value.json"], os.listdir(temporary))

    def test_served_document_is_group_readable_and_state_files_are_private(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            state = root / "state"
            proc.mkdir()
            make_proc(proc, "proc_stat_a.txt")
            stats.run_tick(str(state), str(proc), no_mac=True, now=1000)
            self.assertEqual(0o640, os.stat(state / "stats.json").st_mode & 0o777)
            self.assertEqual(0o600, os.stat(state / "history.json").st_mode & 0o777)
            default_target = root / "default.json"
            stats.write_json_atomic(default_target, {"key": "value"})
            self.assertEqual(0o600, os.stat(default_target).st_mode & 0o777)

    def test_freshness_bands(self) -> None:
        self.assertEqual("fresh", stats.freshness(0, "vps"))
        self.assertEqual("amber", stats.freshness(45, "vps"))
        self.assertEqual("stale", stats.freshness(90, "vps"))
        self.assertEqual("amber", stats.freshness(89, "vps"))
        self.assertEqual("fresh", stats.freshness(89, "mac"))
        self.assertEqual("amber", stats.freshness(90, "mac"))
        self.assertEqual("amber", stats.freshness(179, "mac"))
        self.assertEqual("stale", stats.freshness(180, "mac"))

    def test_mac_parser_uses_real_capture(self) -> None:
        parsed = stats.parse_mac_probe(fixture_text("mac_probe_raw.txt"))
        self.assertEqual(8, parsed["cpu"]["cores"])
        self.assertAlmostEqual(16.0, parsed["memory"]["total_gb"], delta=0.05)
        # 32.2 comes from the second block's 67.76 idle, not the first block's 56.94.
        self.assertEqual(32.2, parsed["cpu"]["busy_pct"])
        self.assertEqual(16384, parsed["page_size"])
        self.assertEqual(8.8, parsed["memory"]["used_gb"])
        self.assertEqual(54.9, parsed["memory"]["used_pct"])
        self.assertEqual(228.3, parsed["disk"]["total_gb"])
        self.assertEqual(39.0, parsed["disk"]["used_gb"])
        self.assertEqual("/System/Volumes/Data", parsed["disk"]["mount"])
        self.assertEqual(2.69, parsed["load"]["1m"])
        self.assertEqual("unlocked", parsed["screen"])
        self.assertIn("\u2019", parsed["name"])

    def test_mac_parser_reads_the_real_lock_flag_not_the_console_owner(self) -> None:
        # Recorded from the Mac while its screen was locked (mac_probe_locked.txt). The console
        # still belongs to prakashsewani in that state — macOS only hands /dev/console to
        # loginwindow at logout — so the console owner reads "unlocked" for a locked Mac. The
        # flag is the answer, and this is the assertion the old parse would have failed.
        locked_text = fixture_text("mac_probe_locked.txt")
        self.assertIn("LOCKED=1", locked_text)
        self.assertEqual("locked", stats.parse_mac_probe(locked_text)["screen"])
        # Unlocked: the ioreg key is absent (or No), and the probe reports 0 for it.
        self.assertEqual(
            "unlocked", stats.parse_mac_probe(locked_text.replace("LOCKED=1", "LOCKED=0"))["screen"]
        )
        # An older probe, recorded before the flag existed, carries no LOCKED line at all.
        # macOS omits the key entirely when the screen is not locked, so absent means unlocked.
        raw_text = fixture_text("mac_probe_raw.txt")
        self.assertNotIn("LOCKED=", raw_text)
        self.assertEqual("unlocked", stats.parse_mac_probe(raw_text)["screen"])

    def test_load_average_comes_from_the_proc_fixture(self) -> None:
        # proc_loadavg.txt is a real /proc/loadavg snapshot, and --proc-dir now reads it: the
        # fixture is exercised instead of being recorded and ignored, which also makes the load
        # path testable off-host.
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            make_proc(proc, "proc_stat_a.txt")
            self.assertEqual((0.61, 0.62, 0.54), stats.read_loadavg(str(proc)))
            sample = stats.sample_vps(str(proc))[0]
            # No loadavg in the proc directory (a stripped-down fixture set) falls back to the
            # host's own numbers rather than failing the tick.
            os.unlink(str(proc / "loadavg"))
            self.assertEqual(os.getloadavg(), stats.read_loadavg(str(proc)))
        self.assertEqual({"1m": 0.61, "5m": 0.62, "15m": 0.54}, sample["load"])

    def test_asleep_and_malformed_mac_are_reported_states(self) -> None:
        def asleep(*args: Any, **kwargs: Any) -> FakeResult:
            return FakeResult(255, "", "Connection timed out")

        def garbage(*args: Any, **kwargs: Any) -> FakeResult:
            return FakeResult(0, "not a probe", "")

        sleeping = stats.mac_sample("mac", runner=asleep, now=100)
        self.assertEqual("asleep", sleeping["status"])
        self.assertEqual("dark", sleeping["field"])
        self.assertIsInstance(sleeping["detail"], str)
        self.assertLessEqual(len(sleeping["detail"]), 160)
        broken = stats.mac_sample("mac", runner=garbage, now=100)
        self.assertEqual("error", broken["status"])
        self.assertEqual("dark", broken["field"])

    def test_frozen_mac_reading_ages_through_freshness_bands(self) -> None:
        mac = stats.mac_sample("mac", runner=successful_mac_runner, now=1000)
        vps: Dict[str, Any] = {
            "kind": "vps",
            "name": "vps",
            "status": "online",
            "generated_at_epoch": 1000,
        }
        history = stats.new_history()
        fresh = stats.build_document(vps, history, mac, now=1000)["hosts"]["mac"]
        amber = stats.build_document(vps, history, mac, now=1090)["hosts"]["mac"]
        stale = stats.build_document(vps, history, mac, now=1180)["hosts"]["mac"]
        self.assertEqual((0, "fresh"), (fresh["age_s"], fresh["field"]))
        self.assertEqual((90, "amber"), (amber["age_s"], amber["field"]))
        self.assertEqual((180, "stale"), (stale["age_s"], stale["field"]))
        self.assertEqual("online", stale["status"])

    def test_document_does_not_leak_secrets(self) -> None:
        def unsafe_failure(*args: Any, **kwargs: Any) -> FakeResult:
            message = "password token secret PRIVATE BEGIN OPENSSH /root authorized_keys"
            return FakeResult(255, "", message)

        mac = stats.mac_sample("mac", runner=unsafe_failure, now=1000)
        vps = {
            "kind": "vps",
            "name": "hermes-vps",
            "status": "online",
            "generated_at": "1970-01-01T00:16:40+0000",
            "generated_at_epoch": 1000,
            "cpu": {"cores": 1, "busy_pct": 1.0},
            "memory": {"used_pct": 1.0},
        }
        serialised = json.dumps(
            stats.build_document(vps, stats.new_history(), mac, now=1000)
        ).lower()
        forbidden = (
            "password",
            "token",
            "secret",
            "private",
            "begin openssh",
            "/root",
            "authorized_keys",
        )
        for term in forbidden:
            self.assertNotIn(term, serialised)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux proc files")
    def test_live_linux_sample_matches_independent_sources(self) -> None:
        sample, unused_pair = stats.sample_vps("/proc")
        del unused_pair
        independent_mem = stats.read_meminfo("/proc")
        independent_disk = shutil.disk_usage("/")
        independent_load = os.getloadavg()
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            independent_uptime = int(float(handle.read().split()[0]))
        self.assertEqual(
            round(independent_mem["MemTotal"] / (1024.0 ** 3), 2),
            sample["memory"]["total_gb"],
        )
        self.assertAlmostEqual(
            round(independent_disk.total / (1024.0 ** 3), 1),
            sample["disk"]["total_gb"],
            delta=0.1,
        )
        self.assertAlmostEqual(independent_load[0], sample["load"]["1m"], delta=0.1)
        self.assertAlmostEqual(independent_uptime, sample["uptime_s"], delta=2)
        self.assertGreaterEqual(sample["cpu"]["busy_pct"], 0)
        self.assertLessEqual(sample["cpu"]["busy_pct"], 100)

    def test_cli_smoke_prints_parseable_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            proc.mkdir()
            make_proc(proc)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = stats.main(
                    [
                        "--state-dir",
                        str(root / "state"),
                        "--proc-dir",
                        str(proc),
                        "--no-mac",
                        "--print",
                        "--json",
                    ]
                )
            self.assertEqual(0, code)
            self.assertEqual(1, json.loads(output.getvalue())["schema"])

    def test_name_flag_overrides_the_plain_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root / "proc"
            proc.mkdir()
            make_proc(proc)
            document = stats.run_tick(
                str(root / "state"), str(proc), no_mac=True, now=1000, name="hermes-vps"
            )
            self.assertEqual("hermes-vps", document["hosts"]["vps"]["name"])
            fallback = stats.sample_vps(str(proc))[0]["name"]
            self.assertTrue(fallback)
            self.assertNotEqual("hermes-vps", fallback)

    def test_version_returns_zero_and_prints_version(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = stats.main(["--version"])
        self.assertEqual(0, code)
        self.assertIn(stats.VERSION, output.getvalue())


if __name__ == "__main__":
    unittest.main()
