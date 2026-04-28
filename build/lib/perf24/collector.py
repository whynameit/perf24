from __future__ import annotations

from pathlib import Path
import os
import signal
import subprocess
import time

from .config import Config


def ensure_directories(config: Config) -> None:
    config.paths.base_dir.mkdir(parents=True, exist_ok=True)
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)
    config.paths.run_dir.mkdir(parents=True, exist_ok=True)
    config.paths.log_file.parent.mkdir(parents=True, exist_ok=True)


def perf_env() -> dict[str, str]:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def build_record_command(config: Config, dry_run: bool = False) -> list[str]:
    cmd = [config.collect.perf_binary, "record"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(
        [
            "-o",
            str(config.paths.data_dir / config.paths.output_name),
            "-e",
            config.collect.event,
            "-F",
            str(config.collect.freq),
            "-g",
            "--call-graph",
            config.collect.call_graph,
            "--switch-output",
            _format_segment_duration(config),
            "--switch-max-files",
            str(config.collect.retain_segments),
            "--clockid",
            config.collect.clockid,
        ]
    )
    if config.collect.system_wide:
        cmd.append("-a")
    if config.collect.timestamp_boundary:
        cmd.append("--timestamp-boundary")
    cmd.extend(config.collect.extra_record_args)
    return cmd


def _format_segment_duration(config: Config) -> str:
    total_seconds = int(config.collect.segment_duration.total_seconds())
    if total_seconds % 86400 == 0:
        return f"{total_seconds // 86400}d"
    if total_seconds % 3600 == 0:
        return f"{total_seconds // 3600}h"
    if total_seconds % 60 == 0:
        return f"{total_seconds // 60}m"
    return f"{total_seconds}s"


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def start_background(config: Config) -> int:
    ensure_directories(config)
    existing_pid = read_pid(config.paths.pid_file)
    if existing_pid and pid_is_running(existing_pid):
        raise RuntimeError(f"collector already running with pid {existing_pid}")
    if config.paths.pid_file.exists():
        config.paths.pid_file.unlink()

    command = build_record_command(config)
    with config.paths.log_file.open("a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(config.paths.data_dir),
            env=perf_env(),
            start_new_session=True,
            close_fds=True,
        )
    config.paths.pid_file.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def stop_background(config: Config, timeout_seconds: float = 30.0) -> bool:
    pid = read_pid(config.paths.pid_file)
    if not pid:
        return False
    if not pid_is_running(pid):
        config.paths.pid_file.unlink(missing_ok=True)
        return False

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not pid_is_running(pid):
            config.paths.pid_file.unlink(missing_ok=True)
            return True
        time.sleep(0.2)

    os.kill(pid, signal.SIGKILL)
    config.paths.pid_file.unlink(missing_ok=True)
    return True


def collector_status(config: Config) -> dict[str, object]:
    pid = read_pid(config.paths.pid_file)
    running = bool(pid and pid_is_running(pid))
    latest_files = sorted(config.paths.data_dir.glob(f"{config.paths.output_name}*"))
    newest = latest_files[-1] if latest_files else None
    return {
        "running": running,
        "pid": pid,
        "log_file": config.paths.log_file,
        "data_dir": config.paths.data_dir,
        "newest_segment": newest,
        "segment_count": len(latest_files),
    }
