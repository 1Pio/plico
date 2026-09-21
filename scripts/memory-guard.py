#!/usr/bin/env python3
"""Run only this build's process group under conservative macOS memory limits."""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

MIB = 1024 * 1024
APP_SUFFIXES = ("/ChatGPT.app/Contents/MacOS/ChatGPT", "/Codex.app/Contents/MacOS/Codex")
# The sysctl returns dispatch flags, not XNU's internal pressure enum.
# kern_memorystatus_notify.c converts Normal -> 1, Warning/Urgent -> 2,
# Critical -> 4 before exposing kern.memorystatus_vm_pressure_level.
PRESSURE_NAMES = {1: "Normal", 2: "Warning", 4: "Critical"}


def kernel_pressure():
    value = int(subprocess.check_output(
        ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"], text=True))
    if value not in PRESSURE_NAMES:
        raise RuntimeError(f"Unknown kernel memory pressure {value}; refusing to proceed.")
    return value


def on_ac_power():
    output = subprocess.check_output(["/usr/bin/pmset", "-g", "batt"], text=True)
    return "Now drawing from 'AC Power'" in output.splitlines()[0]


def app_processes():
    """Find desktop app families even when this guard is owned by launchd."""
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
    identities = {}
    for line in output.splitlines():
        row = line.strip().split(maxsplit=1)
        if len(row) == 2 and row[1].endswith(APP_SUFFIXES):
            pid = int(row[0])
            identity = process_identity(pid)
            if identity is not None:
                identities[pid] = identity
    return process_tree(None, identities, identities)


def write_status(path, **values):
    if path is None:
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"time": time.time(), "pid": os.getpid(), **values}, indent=2) + "\n")
    temporary.replace(path)


def readiness_reason(free, pressure, combined_mib, args, ac=True):
    if pressure != 1:
        return f"kernel memory pressure is {PRESSURE_NAMES[pressure]}"
    if free < args.min_free_percent + 10:
        return f"free memory is {free}%; at least {args.min_free_percent + 10}% is required to start"
    if combined_mib > args.max_host_mib:
        return f"host app and build use {combined_mib:.0f} MiB, exceeding {args.max_host_mib} MiB"
    if args.independent and combined_mib + args.max_build_mib > args.max_host_mib:
        available = args.max_host_mib - combined_mib
        return (f"only {available:.0f} MiB remains within the combined app/build budget; "
                f"{args.max_build_mib} MiB is required before starting")
    if args.require_ac_power and not ac:
        return "waiting for AC power"
    return None


class RUsageInfoV2(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups",
            "pageins", "wired_size", "resident_size", "phys_footprint",
            "proc_start_abstime", "proc_exit_abstime", "child_user_time",
            "child_system_time", "child_pkg_idle_wkups", "child_interrupt_wkups",
            "child_pageins", "child_elapsed_abstime", "diskio_bytesread",
            "diskio_byteswritten",
        )
    ]


def system_memory():
    pressure = subprocess.check_output(["/usr/bin/memory_pressure", "-Q"], text=True)
    swap = subprocess.check_output(["/usr/sbin/sysctl", "-n", "vm.swapusage"], text=True)
    free_match = re.search(r"free percentage:\s*(\d+)%", pressure)
    swap_match = re.search(r"used\s*=\s*([\d.]+)([MG])", swap)
    if not free_match or not swap_match:
        raise RuntimeError("Cannot measure memory pressure or swap; refusing an unmonitored build.")
    used = float(swap_match[1]) * (1024 if swap_match[2] == "G" else 1)
    return int(free_match[1]), used


def process_tree(group, seeds=(), identities=None):
    # Read process IDs only. Do not capture unrelated apps' command arguments.
    output = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid="], text=True)
    rows = [tuple(map(int, line.split())) for line in output.splitlines() if line.strip()]
    identities = identities or {}
    def same_process(pid):
        return pid not in identities or process_identity(pid) == identities[pid]
    tree = {pid for pid, parent, pgid in rows
            if (pgid == group or pid in seeds) and same_process(pid)}
    while True:
        children = {pid for pid, parent, pgid in rows
                    if parent in tree and same_process(pid)}
        if children <= tree:
            return tree
        tree |= children


def footprint(pids):
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    library.proc_pid_rusage.restype = ctypes.c_int
    total = 0
    measured = 0
    for pid in pids:
        data = RUsageInfoV2()
        if library.proc_pid_rusage(pid, 2, ctypes.byref(data)) == 0:
            total += data.phys_footprint
            measured += 1
        elif ctypes.get_errno() not in (3,):  # A process may exit between samples.
            raise RuntimeError(f"Cannot measure build process {pid}.")
    return total / MIB, measured


def process_breakdown(pids):
    """Attribute a stop to owned executable paths, without capturing arguments."""
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    rows = []
    for pid in pids:
        usage, measured = footprint({pid})
        if not measured:
            continue
        path = ctypes.create_string_buffer(4096)
        length = library.proc_pidpath(pid, path, len(path))
        rows.append({"pid": pid, "mib": round(usage, 1),
                     "executable": path.value.decode(errors="replace") if length > 0 else None})
    return sorted(rows, key=lambda row: row["mib"], reverse=True)


def host_app():
    pid = os.getpid()
    for _ in range(32):
        row = subprocess.check_output(
            ["/bin/ps", "-p", str(pid), "-o", "ppid=,comm="], text=True).strip().split(maxsplit=1)
        if len(row) != 2:
            return None
        parent, command = row
        if command.endswith(APP_SUFFIXES):
            return pid, process_identity(pid)
        pid = int(parent)
        if pid <= 1:
            return None
    return None


def breach(free, swap, baseline_swap, build_mib, args, host_mib=None, pressure=1):
    if pressure != 1:
        return f"kernel memory pressure is {PRESSURE_NAMES[pressure]}"
    if free < args.min_free_percent:
        return f"system free memory {free}% is below {args.min_free_percent}%"
    if build_mib > args.max_build_mib:
        return f"build physical footprint {build_mib:.0f} MiB exceeds {args.max_build_mib} MiB"
    if host_mib is not None and host_mib > args.max_host_mib:
        return f"host app and descendants use {host_mib:.0f} MiB, exceeding {args.max_host_mib} MiB"
    if swap - baseline_swap > args.max_swap_growth_mib:
        return f"swap grew by {swap - baseline_swap:.0f} MiB"
    return None


def process_identity(pid):
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    library.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    data = RUsageInfoV2()
    if library.proc_pid_rusage(pid, 2, ctypes.byref(data)) == 0:
        return None if data.proc_exit_abstime else data.proc_start_abstime
    if ctypes.get_errno() == 3:
        return None
    raise RuntimeError(f"Cannot identify build process {pid}.")


class OwnedProcesses:
    """Retain identities of workers that make their own process groups."""
    def __init__(self, child):
        self.child = child
        self.identities = {}

    def known_live(self):
        return {pid for pid, identity in self.identities.items()
                if process_identity(pid) == identity}

    def owns_original_group(self, live):
        # Before wait/poll reaps the child, its PID cannot be reused. Afterward
        # require a verified member, including when a worker outlives Siso.
        if self.child.returncode is None:
            return True
        for pid in live:
            try:
                if os.getpgid(pid) == self.child.pid:
                    return True
            except ProcessLookupError:
                pass
        return False

    def refresh(self):
        live = self.known_live()
        group = self.child.pid if self.owns_original_group(live) else None
        for pid in process_tree(group, live, self.identities):
            identity = process_identity(pid)
            if identity is not None:
                self.identities.setdefault(pid, identity)
                if self.identities[pid] == identity:
                    live.add(pid)
        return live

    def signal(self, sig):
        try:
            live = self.refresh()
        except Exception as error:
            # Discovery failure must not prevent cleanup of already-owned work.
            print(f"Process discovery failed during cleanup: {error}", file=sys.stderr)
            live = self.known_live()
        # Group signaling also covers a newly spawned worker between snapshots.
        # The group is dedicated to this child; Codex is in a different group.
        if self.owns_original_group(live):
            try:
                os.killpg(self.child.pid, sig)
            except ProcessLookupError:
                pass
        for pid in live:
            if process_identity(pid) == self.identities[pid]:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass


def stop_group(owned, delays=(10, 5, 5)):
    # Continue escalation after the scheduler exits. Siso workers can have
    # separate groups; their recorded start identities prevent PID-reuse kills.
    for sig, delay in zip((signal.SIGINT, signal.SIGTERM, signal.SIGKILL), delays):
        owned.signal(sig)
        deadline = time.monotonic() + delay
        while True:
            try:
                live = owned.refresh()
            except Exception:
                live = owned.known_live()
            owned.child.poll()
            if not live:
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    survivors = owned.known_live()
    if survivors:
        raise RuntimeError(f"Build processes survived shutdown: {sorted(survivors)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-build-mib", type=int, default=6144)
    parser.add_argument("--max-host-mib", type=int, default=14336)
    parser.add_argument("--min-free-percent", type=int, default=35)
    parser.add_argument("--max-swap-growth-mib", type=int, default=512)
    parser.add_argument("--independent", action="store_true",
                        help="Require app-independent ancestry and monitor all desktop app families")
    parser.add_argument("--wait-for-headroom-seconds", type=int, default=0)
    parser.add_argument("--max-runtime-seconds", type=int, default=0)
    parser.add_argument("--require-ac-power", action="store_true")
    parser.add_argument("--status", type=Path)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required")
    if not 0 <= args.wait_for_headroom_seconds <= 43200:
        parser.error("headroom wait must be between 0 and 43200 seconds")
    if args.max_runtime_seconds < 0:
        parser.error("runtime limit cannot be negative")
    if args.wait_for_headroom_seconds and not args.independent:
        parser.error("waiting for headroom requires independent supervision")
    if args.status and args.status.parent.resolve() != args.log.parent.resolve():
        parser.error("status and telemetry must share the guarded log directory")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    lock = (args.log.parent / "memory-guard.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another guarded operation is already using this build directory.")
    interrupted = []
    def on_signal(sig, frame):
        interrupted.append(sig)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    host = host_app()
    if args.independent and host:
        raise SystemExit("Independent mode requires launchd ancestry, not a desktop-app child.")
    own, count = footprint({os.getpid()})
    if count != 1 or own <= 0:
        raise SystemExit("Cannot verify native process footprint accounting.")
    deadline = time.monotonic() + args.wait_for_headroom_seconds
    ready_since = None
    previous_reason = None
    while True:
        if interrupted:
            write_status(args.status, state="canceled", exit_code=128 + interrupted[0])
            return 128 + interrupted[0]
        free, baseline_swap = system_memory()
        pressure = kernel_pressure()
        if host and process_identity(host[0]) != host[1]:
            raise SystemExit("Host app exited before the build started.")
        tracked = app_processes() if args.independent else (process_tree(None, {host[0]}) if host else set())
        combined_mib, _ = footprint(tracked | {os.getpid()})
        reason = readiness_reason(free, pressure, combined_mib, args,
                                  on_ac_power() if args.require_ac_power else True)
        now = time.monotonic()
        if reason:
            ready_since = None
        elif ready_since is None:
            ready_since = now
        # Independent queued jobs require a stable 15-second readiness window.
        if not reason and (not args.wait_for_headroom_seconds or now - ready_since >= 15):
            break
        status = reason or "confirming stable memory headroom"
        write_status(args.status, state="waiting", reason=status, free_percent=free,
                     pressure=PRESSURE_NAMES[pressure], combined_mib=round(combined_mib, 1),
                     wait_deadline=time.time() + max(0, deadline - now))
        if status != previous_reason:
            print("Build held: " + status, flush=True)
            previous_reason = status
        if not args.wait_for_headroom_seconds or now >= deadline:
            write_status(args.status, state="held", reason=status, exit_code=75)
            return 75
        time.sleep(min(5, max(0, deadline - now)))
    env = os.environ.copy()
    env["PYTHON_CPU_COUNT"] = "1"
    env["GRIT_DISABLE_MULTIPROCESSING"] = "1"
    env["NODE_OPTIONS"] = "--max-old-space-size=2048"
    env["GOMAXPROCS"] = "2"
    env["GOMEMLIMIT"] = "1536MiB"
    child = subprocess.Popen(command, env=env, start_new_session=True)
    owned = OwnedProcesses(child)
    minimum_swap = baseline_swap
    started = time.monotonic()
    outcome = "exited"
    exit_code = None
    try:
        write_status(args.status, state="running", child_pid=child.pid, independent=args.independent)
        owned.refresh()
        with args.log.open("a", buffering=1) as log:
            while True:
                pids = owned.refresh()
                if child.poll() is not None:
                    break
                if interrupted:
                    outcome, exit_code = "canceled", 128 + interrupted[0]
                    return exit_code
                if args.max_runtime_seconds and time.monotonic() - started >= args.max_runtime_seconds:
                    outcome, exit_code = "time_limit", 124
                    print("Build stopped at its deliberate calibration time limit.", flush=True)
                    return exit_code
                free, swap = system_memory()
                pressure = kernel_pressure()
                minimum_swap = min(minimum_swap, swap)
                usage, count = footprint(pids)
                host_mib = None
                if args.independent:
                    # Union avoids double counting if an app happens to parent a worker.
                    host_mib, _ = footprint(app_processes() | pids | {os.getpid()})
                elif host:
                    if process_identity(host[0]) != host[1]:
                        print("Host app exited; stopping owned build.", file=sys.stderr)
                        outcome, exit_code = "host_exited", 75
                        return exit_code
                    host_mib, _ = footprint(process_tree(None, {host[0]}))
                log.write(json.dumps({"time": time.time(), "build_mib": round(usage, 1),
                    "processes": count, "free_percent": free, "swap_mib": swap,
                    "host_mib": round(host_mib, 1) if host_mib is not None else None,
                    "kernel_pressure": pressure, "independent": args.independent}) + "\n")
                reason = breach(free, swap, minimum_swap, usage, args, host_mib, pressure)
                if not reason and args.require_ac_power and not on_ac_power():
                    reason = "AC power disconnected"
                if reason:
                    print("Memory guard stopped build: " + reason, file=sys.stderr, flush=True)
                    try:
                        log.write(json.dumps({"time": time.time(), "stop_reason": reason,
                            "owned_processes": process_breakdown(owned.known_live())}) + "\n")
                    except Exception as error:
                        print(f"Stop attribution unavailable: {error}", file=sys.stderr)
                    outcome, exit_code = "guard_stop", 75
                    return exit_code
                time.sleep(1)
    except BaseException:
        outcome, exit_code = "monitor_error", 1
        raise
    finally:
        stop_group(owned)
        result = exit_code if exit_code is not None else (128 + interrupted[0] if interrupted else child.returncode)
        write_status(args.status, state=outcome, exit_code=result,
                     elapsed_seconds=round(time.monotonic() - started, 1))
    return 128 + interrupted[0] if interrupted else child.returncode


if __name__ == "__main__":
    sys.exit(main())
