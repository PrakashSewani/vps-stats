"""Collect VPS and optional Mac statistics; run with ``python3 exporter/stats.py``."""

from __future__ import annotations

import argparse
import copy
import datetime as _datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

VERSION = "1.0.0"
_GIB = 1024.0 ** 3
# A CPU delta is only a measurement of the box when the window between the two readings is long
# enough not to be dominated by the sampler itself: starting a Python interpreter costs about a
# tenth of a second of CPU, so a window of a few hundred milliseconds reads ~100% busy on an
# idle box. Measured on this 1-vCPU host, four back-to-back ticks reported 100.0/100.0/91.7%
# while the lifetime average at the same moment was 5.6%. systemd can bunch ticks like that:
# `OnUnitActiveSec` is recomputed from the last *activation*, so a tick that outruns the
# interval leaves the next elapse already in the past. Windows shorter than this floor fall back
# to the lifetime average instead of reporting a number that is not about the machine.
MIN_CPU_DELTA_WINDOW_S = 5.0

MAC_PROBE = r'''echo "HOST=$(scutil --get ComputerName 2>/dev/null || hostname)"
echo "MODEL=$(sysctl -n machdep.cpu.brand_string 2>/dev/null)"
echo "CORES=$(sysctl -n hw.ncpu 2>/dev/null)"
echo "TOTAL=$(sysctl -n hw.memsize 2>/dev/null)"
echo "BOOTTIME=$(sysctl -n kern.boottime 2>/dev/null)"
echo "LOAD=$(sysctl -n vm.loadavg 2>/dev/null)"
# Ground truth for the screen field. ``stat -f%Su /dev/console`` looked like the answer but is
# not one: macOS keeps the logged-in user as the console owner while the screen is locked (the
# login window only takes the console at logout), so the console owner reads "unlocked" for a
# Mac that is locked. ``CGSSessionScreenIsLocked`` is the authoritative flag; it prints 1 only
# when the screen really is locked (the key is present-but-No, or absent entirely, when it is
# not), so the shell reduces it to that one digit for us.
echo "LOCKED=$(ioreg -n Root -d1 | tr ',' '\n' | grep -m1 'CGSSessionScreenIsLocked' | grep -c 'Yes')"
echo "SWAP=$(sysctl -n vm.swapusage 2>/dev/null)"
echo "--- TOP ---"
top -l 2 -n 0 -s 1 2>/dev/null
echo "--- VMSTAT ---"
vm_stat 2>/dev/null
echo "--- DF ---"
df -k /System/Volumes/Data / 2>/dev/null
echo "--- END ---"'''

JsonObject = Dict[str, Any]
CpuPair = Tuple[int, int]


def _timestamp(epoch: int) -> str:
    return _datetime.datetime.fromtimestamp(epoch).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def uptime_human(seconds: int) -> str:
    """Format an uptime without implying more precision than minutes."""
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days:
        return "{}d {}h".format(days, hours % 24)
    if hours:
        return "{}h {}m".format(hours, minutes % 60)
    return "{}m".format(minutes)


def freshness(age_s: int, kind: str) -> str:
    """Return the freshness band for a host reading."""
    amber, stale = (90, 180) if kind == "mac" else (45, 90)
    age_s = max(0, int(age_s))
    if age_s >= stale:
        return "stale"
    if age_s >= amber:
        return "amber"
    return "fresh"


def read_cpu_times(proc_dir: str) -> CpuPair:
    """Read total and idle scheduler ticks from the aggregate proc stat line."""
    stat_path = Path(proc_dir) / "stat"
    with stat_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("cpu "):
                fields = [int(value) for value in line.split()[1:]]
                if len(fields) < 4:
                    raise ValueError("aggregate CPU line has too few fields")
                total = sum(fields)
                idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
                if total <= 0:
                    raise ValueError("aggregate CPU total is not positive")
                return total, idle
    raise ValueError("aggregate CPU line is missing")


def cpu_busy_pct(
    current: CpuPair,
    previous: Optional[CpuPair] = None,
    window_s: Optional[float] = None,
) -> float:
    """Calculate CPU busy percentage, preferring a delta over a plausible window.

    The delta is taken only when the caller can also say how long the window was and that
    window is at least ``MIN_CPU_DELTA_WINDOW_S``. Without a trustworthy window the lifetime
    average is the honest number — see the constant for what the short-window failure looks
    like on a real box.
    """
    total, idle = current
    use_total, use_idle = total, idle
    if previous is not None and window_s is not None and window_s >= MIN_CPU_DELTA_WINDOW_S:
        delta_total = total - previous[0]
        delta_idle = idle - previous[1]
        if delta_total > 0 and 0 <= delta_idle <= delta_total:
            use_total, use_idle = delta_total, delta_idle
    if use_total <= 0:
        raise ValueError("CPU total is not positive")
    value = 100.0 * (1.0 - float(use_idle) / float(use_total))
    return round(min(100.0, max(0.0, value)), 1)


def read_meminfo(proc_dir: str) -> Dict[str, int]:
    """Read proc memory values and return bytes keyed by their proc labels."""
    values: Dict[str, int] = {}
    with (Path(proc_dir) / "meminfo").open("r", encoding="utf-8") as handle:
        for line in handle:
            key, separator, remainder = line.partition(":")
            if not separator:
                continue
            parts = remainder.split()
            if not parts:
                continue
            try:
                amount = int(parts[0])
            except ValueError:
                continue
            multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
            values[key] = amount * multiplier
    return values


def memory_stats(values: Mapping[str, int]) -> Tuple[JsonObject, JsonObject]:
    """Build memory and swap blocks from byte-valued proc memory data."""
    total = values["MemTotal"]
    available = values["MemAvailable"]
    used = max(0, total - available)
    swap_total = values.get("SwapTotal", 0)
    swap_free = values.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    memory = {
        "total_gb": round(total / _GIB, 2),
        "used_gb": round(used / _GIB, 2),
        "used_pct": round(100.0 * used / total, 1) if total else 0.0,
        "available_gb": round(available / _GIB, 2),
    }
    swap = {
        "total_gb": round(swap_total / _GIB, 1),
        "used_gb": round(swap_used / _GIB, 1),
        "used_pct": round(100.0 * swap_used / swap_total, 1) if swap_total else 0.0,
    }
    return memory, swap


def read_uptime(proc_dir: str) -> int:
    """Read uptime from proc, with a guarded Linux clock fallback."""
    try:
        with (Path(proc_dir) / "uptime").open("r", encoding="utf-8") as handle:
            return max(0, int(float(handle.read().split()[0])))
    except (OSError, ValueError, IndexError):
        pass
    try:
        clock = getattr(time, "CLOCK_BOOTTIME")
        return max(0, int(time.clock_gettime(clock)))
    except (AttributeError, OSError, ValueError):
        return max(0, int(time.monotonic()))


def read_loadavg(proc_dir: str) -> Tuple[float, float, float]:
    """Read the three load averages from proc, falling back to the host's own numbers."""
    try:
        with (Path(proc_dir) / "loadavg").open("r", encoding="utf-8") as handle:
            fields = handle.read().split()
        return float(fields[0]), float(fields[1]), float(fields[2])
    except (OSError, ValueError, IndexError):
        return os.getloadavg()


def _cpu_cores(proc_dir: str) -> int:
    try:
        with (Path(proc_dir) / "stat").open("r", encoding="utf-8") as handle:
            count = sum(1 for line in handle if re.match(r"^cpu\d+\s", line))
        if count:
            return count
    except OSError:
        pass
    return os.cpu_count() or 1


def _previous_sample(previous: Optional[Mapping[str, Any]]) -> Tuple[Optional[CpuPair], Optional[int]]:
    """Split a stored previous sample into its CPU pair and the epoch it was taken at.

    A previous file without ``at`` (written before the window was recorded) yields no pair, so
    the first tick after an upgrade reports the lifetime average rather than an unmeasurable
    delta. Self-healing: the next tick writes a complete record.
    """
    if not previous:
        return None, None
    try:
        pair = (int(previous["total"]), int(previous["idle"]))
    except (KeyError, TypeError, ValueError):
        return None, None
    taken = previous.get("at")
    return pair, int(taken) if isinstance(taken, int) else None


def sample_vps(
    proc_dir: str = "/proc",
    previous: Optional[Mapping[str, Any]] = None,
    now: Optional[int] = None,
    name: Optional[str] = None,
) -> Tuple[JsonObject, CpuPair]:
    """Take one local sample and return it with the CPU pair to persist."""
    epoch = int(time.time()) if now is None else int(now)
    pair = read_cpu_times(proc_dir)
    previous_pair, previous_at = _previous_sample(previous)
    window_s = None if previous_at is None else float(epoch - previous_at)
    memory, swap = memory_stats(read_meminfo(proc_dir))
    disk_usage = shutil.disk_usage("/")
    load = read_loadavg(proc_dir)
    uptime_s = read_uptime(proc_dir)
    # The hostname is plain (this box calls itself "vps"); --name lets the installer put the
    # tailnet name on the card instead, which is the name the reader typed in the address bar.
    shown_name = (name or os.environ.get("VPS_STATS_NAME") or "").strip()
    if not shown_name:
        shown_name = socket.gethostname().split(".", 1)[0]
    sample: JsonObject = {
        "kind": "vps",
        "name": shown_name,
        "status": "online",
        "generated_at": _timestamp(epoch),
        "generated_at_epoch": epoch,
        "age_s": 0,
        "field": "fresh",
        "cpu": {"cores": _cpu_cores(proc_dir), "busy_pct": cpu_busy_pct(pair, previous_pair, window_s)},
        "memory": memory,
        "swap": swap,
        "disk": {
            "mount": "/",
            "total_gb": round(disk_usage.total / _GIB, 1),
            "used_gb": round(disk_usage.used / _GIB, 1),
            "used_pct": (
                round(100.0 * disk_usage.used / disk_usage.total, 1)
                if disk_usage.total
                else 0.0
            ),
            "free_gb": round(disk_usage.free / _GIB, 1),
        },
        "load": {"1m": round(load[0], 2), "5m": round(load[1], 2), "15m": round(load[2], 2)},
        "uptime_s": uptime_s,
        "uptime": uptime_human(uptime_s),
    }
    return sample, pair


def _sectioned_probe(text: str) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    scalars: Dict[str, str] = {}
    sections: Dict[str, List[str]] = {"TOP": [], "VMSTAT": [], "DF": []}
    section: Optional[str] = None
    for line in text.splitlines():
        marker = re.match(r"^--- (TOP|VMSTAT|DF|END) ---$", line.strip())
        if marker:
            section = None if marker.group(1) == "END" else marker.group(1)
            continue
        if section is not None:
            sections[section].append(line)
        elif not sections["TOP"] and "=" in line:
            key, value = line.split("=", 1)
            scalars[key.strip()] = value.strip()
    return scalars, sections


def _number(text: Optional[str], integer: bool = False) -> Optional[Any]:
    if text is None:
        return None
    try:
        return int(text.strip()) if integer else float(text.strip())
    except (TypeError, ValueError):
        return None


def _vm_pages(lines: Sequence[str]) -> Tuple[int, Dict[str, int]]:
    page_size = 16384
    pages: Dict[str, int] = {}
    for line in lines:
        size_match = re.search(r"page size of\s+(\d+)\s+bytes", line)
        if size_match:
            page_size = int(size_match.group(1))
        label, separator, value = line.partition(":")
        if not separator:
            continue
        match = re.search(r"(\d+)", value)
        if match:
            pages[label.strip().strip('"')] = int(match.group(1))
    return page_size, pages


def _swap_gb(value: str, key: str) -> Optional[float]:
    match = re.search(r"\b{}\s*=\s*([0-9.]+)\s*([MG])".format(key), value, re.I)
    if not match:
        return None
    amount = float(match.group(1))
    if match.group(2).upper() == "M":
        amount /= 1024.0
    return round(amount, 1)


def _parse_mac_disk(lines: Sequence[str]) -> Optional[JsonObject]:
    candidates: Dict[str, JsonObject] = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 6 or not parts[-1].startswith("/"):
            continue
        try:
            total_kb = int(parts[1])
            used_kb = int(parts[2])
            free_kb = int(parts[3])
        except ValueError:
            continue
        mount = parts[-1]
        candidates[mount] = {
            "mount": mount,
            "total_gb": round(total_kb * 1024 / _GIB, 1),
            "used_gb": round(used_kb * 1024 / _GIB, 1),
            "used_pct": round(100.0 * used_kb / total_kb, 1) if total_kb else 0.0,
            "free_gb": round(free_kb * 1024 / _GIB, 1),
        }
    return candidates.get("/System/Volumes/Data") or candidates.get("/")


def parse_mac_probe(text: str) -> JsonObject:
    """Parse a recorded macOS probe without performing I/O or consulting the clock."""
    scalars, sections = _sectioned_probe(text)
    idle_values: List[float] = []
    for line in sections["TOP"]:
        if "CPU usage:" not in line:
            continue
        match = re.search(r"([0-9.]+)%\s*idle", line)
        if match:
            idle_values.append(float(match.group(1)))
    busy_pct = round(100.0 - idle_values[-1], 1) if idle_values else None

    page_size, pages = _vm_pages(sections["VMSTAT"])
    total = _number(scalars.get("TOTAL"), integer=True)
    memory: Optional[JsonObject] = None
    required_pages = ("Pages active", "Pages wired down", "Pages occupied by compressor")
    if total is not None and total > 0 and all(label in pages for label in required_pages):
        used = sum(pages[label] for label in required_pages) * page_size
        used = min(int(total), used)
        free = (pages.get("Pages free", 0) + pages.get("Pages speculative", 0)) * page_size
        cached = pages.get("Pages inactive", 0) * page_size
        memory = {
            "total_gb": round(int(total) / _GIB, 1),
            "used_gb": round(used / _GIB, 1),
            "used_pct": round(100.0 * used / int(total), 1),
            "free_gb": round(free / _GIB, 1),
            "cached_gb": round(cached / _GIB, 1),
        }

    load_values = re.findall(r"[-+]?[0-9]*\.?[0-9]+", scalars.get("LOAD", ""))
    load: Optional[JsonObject] = None
    if len(load_values) >= 3:
        load = {
            "1m": round(float(load_values[0]), 2),
            "5m": round(float(load_values[1]), 2),
            "15m": round(float(load_values[2]), 2),
        }
    boot_match = re.search(r"\bsec\s*=\s*(\d+)", scalars.get("BOOTTIME", ""))
    # Only the flag's "1" means locked; "0", an empty value and a missing line all mean the
    # screen is not locked. See MAC_PROBE for why the console owner is not consulted.
    screen = "locked" if scalars.get("LOCKED", "").strip() == "1" else "unlocked"
    swap_value = scalars.get("SWAP", "")
    return {
        "name": scalars.get("HOST") or None,
        "model": scalars.get("MODEL") or None,
        "cpu": {"cores": _number(scalars.get("CORES"), integer=True), "busy_pct": busy_pct},
        "memory": memory,
        "swap": {
            "total_gb": _swap_gb(swap_value, "total"),
            "used_gb": _swap_gb(swap_value, "used"),
        },
        "disk": _parse_mac_disk(sections["DF"]),
        "load": load,
        "screen": screen,
        "boot_time_epoch": int(boot_match.group(1)) if boot_match else None,
        "page_size": page_size,
    }


def _safe_detail(value: str) -> str:
    detail = " ".join((value or "").split())[:160]
    for pattern in (
        r"password",
        r"token",
        r"secret",
        r"private",
        r"BEGIN\s+OPENSSH",
        r"/root",
        r"authorized_keys",
    ):
        detail = re.sub(pattern, "[redacted]", detail, flags=re.I)
    return detail or "No diagnostic output"


def _mac_success(parsed: JsonObject, now: int) -> JsonObject:
    boot = parsed.get("boot_time_epoch")
    uptime_s = max(0, now - boot) if isinstance(boot, int) else None
    sample: JsonObject = {
        "kind": "mac",
        "name": parsed.get("name") or "Mac",
        "model": parsed.get("model"),
        "status": "online",
        "generated_at": _timestamp(now),
        "generated_at_epoch": now,
        "checked_at_epoch": now,
        "age_s": 0,
        "field": "fresh",
        "detail": None,
        "cpu": parsed["cpu"],
        "memory": parsed["memory"],
        "swap": parsed["swap"],
        "disk": parsed["disk"],
        "load": parsed["load"],
        "screen": parsed["screen"],
    }
    if uptime_s is not None:
        sample["uptime_s"] = uptime_s
        sample["uptime"] = uptime_human(uptime_s)
    return sample


def mac_sample(
    host: str = "mac",
    runner: Callable[..., Any] = subprocess.run,
    now: Optional[int] = None,
) -> JsonObject:
    """Probe the Mac once and return an online, asleep, or error state."""
    epoch = int(time.time()) if now is None else int(now)
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=accept-new",
        host,
        MAC_PROBE,
    ]
    try:
        result = runner(command, capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return {
            "kind": "mac",
            "name": "Mac",
            "status": "asleep",
            "checked_at_epoch": epoch,
            "field": "dark",
            "detail": "SSH probe timed out",
        }
    except OSError as error:
        return {
            "kind": "mac",
            "name": "Mac",
            "status": "error",
            "checked_at_epoch": epoch,
            "field": "dark",
            "detail": _safe_detail(str(error)),
        }
    if result.returncode != 0:
        return {
            "kind": "mac",
            "name": "Mac",
            "status": "asleep" if result.returncode == 255 else "error",
            "checked_at_epoch": epoch,
            "field": "dark",
            "detail": _safe_detail(result.stderr),
        }
    parsed = parse_mac_probe(result.stdout)
    cpu = parsed.get("cpu") or {}
    if cpu.get("busy_pct") is None or parsed.get("memory") is None:
        return {
            "kind": "mac",
            "name": parsed.get("name") or "Mac",
            "status": "error",
            "checked_at_epoch": epoch,
            "field": "dark",
            "detail": "Mac probe output did not contain usable CPU and memory data",
        }
    return _mac_success(parsed, epoch)


def new_history(interval_s: int = 15, mac_interval_s: int = 60, capacity: int = 240) -> JsonObject:
    """Create an empty bounded-history document."""
    return {
        "schema": 1,
        "interval_s": interval_s,
        "mac_interval_s": mac_interval_s,
        "capacity": capacity,
        "vps": {"t": [], "cpu_pct": [], "mem_pct": []},
        "mac": {"t": [], "cpu_pct": [], "mem_pct": [], "status": []},
    }


def push_history(
    history: MutableMapping[str, Any],
    kind: str,
    timestamp: int,
    cpu_pct: Optional[float],
    mem_pct: Optional[float],
    capacity: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    """Append one point and trim all parallel arrays in place."""
    if kind not in ("vps", "mac"):
        raise ValueError("history kind must be 'vps' or 'mac'")
    limit = int(history.get("capacity", 240) if capacity is None else capacity)
    if limit <= 0:
        raise ValueError("history capacity must be positive")
    series = history[kind]
    series["t"].append(int(timestamp))
    series["cpu_pct"].append(cpu_pct)
    series["mem_pct"].append(mem_pct)
    keys = ["t", "cpu_pct", "mem_pct"]
    if kind == "mac":
        series["status"].append(status or "online")
        keys.append("status")
    for key in keys:
        if len(series[key]) > limit:
            del series[key][:-limit]
    assert len({len(series[key]) for key in keys}) == 1


def assert_history(history: Mapping[str, Any]) -> None:
    """Assert that every history series is parallel and within its bound."""
    capacity = int(history["capacity"])
    for kind in ("vps", "mac"):
        keys = ["t", "cpu_pct", "mem_pct"] + (["status"] if kind == "mac" else [])
        lengths = {len(history[kind][key]) for key in keys}
        assert len(lengths) == 1
        assert next(iter(lengths)) <= capacity


def write_json_atomic(path: Any, value: Any, mode: int = 0o600) -> None:
    """Replace a JSON file atomically using a temporary sibling and an explicit mode."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            # Set the mode on the open descriptor, before os.replace, so the target is never
            # briefly readable with mkstemp's 0600 (or anything else) after the rename.
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, str(target))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Optional[JsonObject]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _load_previous(path: Path) -> Optional[JsonObject]:
    """Read the stored previous CPU pair together with the epoch it was taken at."""
    value = _read_json(path)
    if value is None:
        return None
    try:
        return {"total": int(value["total"]), "idle": int(value["idle"]), "at": int(value["at"])}
    except (KeyError, TypeError, ValueError):
        return None


def _load_history(path: Path, interval_s: int, mac_interval_s: int, capacity: int) -> JsonObject:
    history = _read_json(path)
    try:
        if history is None or history.get("schema") != 1:
            raise ValueError
        for kind in ("vps", "mac"):
            for key in ("t", "cpu_pct", "mem_pct"):
                if not isinstance(history[kind][key], list):
                    raise ValueError
        if not isinstance(history["mac"]["status"], list):
            raise ValueError
        assert_history(history)
    except (AssertionError, KeyError, TypeError, ValueError):
        history = new_history(interval_s, mac_interval_s, capacity)
    history["interval_s"] = interval_s
    history["mac_interval_s"] = mac_interval_s
    history["capacity"] = capacity
    for kind in ("vps", "mac"):
        keys = ["t", "cpu_pct", "mem_pct"] + (["status"] if kind == "mac" else [])
        for key in keys:
            if len(history[kind][key]) > capacity:
                del history[kind][key][:-capacity]
    assert_history(history)
    return history


def _aged_host(host: Mapping[str, Any], now: int) -> JsonObject:
    result = copy.deepcopy(dict(host))
    generated = result.get("generated_at_epoch")
    age = max(0, now - generated) if isinstance(generated, int) else 0
    result["age_s"] = age
    result["field"] = (
        freshness(age, str(result.get("kind", "vps")))
        if result.get("status") == "online"
        else "dark"
    )
    return result


def build_document(
    vps: Mapping[str, Any],
    history: Mapping[str, Any],
    mac: Optional[Mapping[str, Any]] = None,
    now: Optional[int] = None,
    interval_s: Optional[int] = None,
) -> JsonObject:
    """Build the served document, recalculating each host's true age."""
    epoch = int(time.time()) if now is None else int(now)
    hosts: JsonObject = {"vps": _aged_host(vps, epoch)}
    if mac is not None:
        hosts["mac"] = _aged_host(mac, epoch)
    return {
        "schema": 1,
        "version": VERSION,
        "generated_at": _timestamp(epoch),
        "generated_at_epoch": epoch,
        "interval_s": int(history.get("interval_s", 15) if interval_s is None else interval_s),
        "hosts": hosts,
        "history": copy.deepcopy(dict(history)),
    }


def _merge_failed_mac(last_good: Optional[JsonObject], failure: JsonObject, now: int) -> JsonObject:
    if last_good is None:
        result = copy.deepcopy(failure)
        result["age_s"] = 0
        return result
    result = copy.deepcopy(last_good)
    result["status"] = failure["status"]
    result["checked_at_epoch"] = now
    result["detail"] = failure.get("detail")
    result["field"] = "dark"
    generated = result.get("generated_at_epoch")
    result["age_s"] = max(0, now - generated) if isinstance(generated, int) else 0
    return result


def run_tick(
    state_dir: str,
    proc_dir: str = "/proc",
    mac_host: str = "mac",
    interval_s: int = 15,
    mac_interval_s: int = 60,
    capacity: int = 240,
    no_mac: bool = False,
    force_mac: bool = False,
    now: Optional[int] = None,
    mac_runner: Callable[..., Any] = subprocess.run,
    name: Optional[str] = None,
) -> JsonObject:
    """Take one complete tick, update state atomically, and return the served document."""
    epoch = int(time.time()) if now is None else int(now)
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    previous = _load_previous(directory / "prev.json")
    vps, pair = sample_vps(proc_dir, previous, epoch, name)
    history = _load_history(directory / "history.json", interval_s, mac_interval_s, capacity)
    push_history(
        history,
        "vps",
        epoch,
        vps["cpu"]["busy_pct"],
        vps["memory"]["used_pct"],
        capacity,
    )

    last_good = _read_json(directory / "mac.json")
    mac: Optional[JsonObject] = copy.deepcopy(last_good)
    fresh_mac = False
    if not no_mac:
        generated = last_good.get("generated_at_epoch") if last_good else None
        due = force_mac or not isinstance(generated, int) or epoch - generated >= mac_interval_s
        if due:
            attempt = mac_sample(mac_host, runner=mac_runner, now=epoch)
            if attempt["status"] == "online":
                mac = attempt
                fresh_mac = True
                write_json_atomic(directory / "mac.json", attempt)
            else:
                mac = _merge_failed_mac(last_good, attempt, epoch)
    if fresh_mac and mac is not None:
        push_history(
            history,
            "mac",
            int(mac["generated_at_epoch"]),
            mac["cpu"].get("busy_pct"),
            mac["memory"].get("used_pct"),
            capacity,
            mac["status"],
        )
    assert_history(history)
    document = build_document(vps, history, mac, epoch, interval_s)
    # The tick time is stored with the counters: without it the next tick cannot tell a 15 s
    # window from a 0.1 s one, and a bunched tick would report the sampler's own CPU.
    write_json_atomic(directory / "prev.json", {"total": pair[0], "idle": pair[1], "at": epoch})
    write_json_atomic(directory / "history.json", history)
    # The served document carries no secret and must be readable by the web server through the
    # state directory's group, while the private state files are nobody's business but the
    # exporter's. Hence 0640 here and the 0600 default everywhere else.
    write_json_atomic(directory / "stats.json", document, mode=0o640)
    return document


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sample VPS and optional Mac statistics")
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("VPS_STATS_STATE_DIR", "/var/lib/vps-stats"),
    )
    parser.add_argument("--proc-dir", default=os.environ.get("VPS_STATS_PROC_DIR", "/proc"))
    parser.add_argument("--mac-host", default=os.environ.get("VPS_STATS_MAC_HOST", "mac"))
    parser.add_argument("--name", default=os.environ.get("VPS_STATS_NAME"))
    parser.add_argument("--interval", type=_positive, default=15)
    parser.add_argument("--mac-interval", type=_positive, default=60)
    parser.add_argument("--capacity", type=_positive, default=240)
    parser.add_argument("--no-mac", action="store_true")
    parser.add_argument("--force-mac", action="store_true")
    parser.add_argument("--print", dest="print_output", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--version", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the command-line sampler and return its documented exit code."""
    arguments = _parser().parse_args(argv)
    if arguments.version:
        print("stats.py {}".format(VERSION))
        return 0
    try:
        document = run_tick(
            state_dir=arguments.state_dir,
            proc_dir=arguments.proc_dir,
            mac_host=arguments.mac_host,
            interval_s=arguments.interval,
            mac_interval_s=arguments.mac_interval,
            capacity=arguments.capacity,
            no_mac=arguments.no_mac,
            force_mac=arguments.force_mac,
            name=arguments.name,
        )
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
        print("VPS sample failed: {}".format(error), file=sys.stderr)
        return 2
    if arguments.print_output:
        if arguments.json:
            print(json.dumps(document, ensure_ascii=False, separators=(",", ":")))
        else:
            vps = document["hosts"]["vps"]
            print(
                "{}: CPU {}%, memory {}%, load {}".format(
                    vps["name"],
                    vps["cpu"]["busy_pct"],
                    vps["memory"]["used_pct"],
                    vps["load"]["1m"],
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
