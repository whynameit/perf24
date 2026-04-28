from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
import re
import tomllib


DEFAULT_CONFIG_TEXT = """[paths]
base_dir = "/var/lib/perf24"
data_dir = "/var/lib/perf24/data"
run_dir = "/var/run/perf24"
log_file = "/var/log/perf24/collector.log"
pid_file = "/var/run/perf24/perf24.pid"
output_name = "perf.data"

[collect]
perf_binary = "perf"
event = "cpu-clock"
freq = 49
call_graph = "fp"
segment_duration = "1m"
retain_segments = 10080
clockid = "CLOCK_REALTIME"
system_wide = true
timestamp_boundary = true
extra_record_args = []

[export]
include_comm_root = true
svg_width = 1600
min_frame_width = 0.1
"""


_DURATION_RE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[smhd]?)$")


@dataclass(slots=True)
class PathsConfig:
    base_dir: Path
    data_dir: Path
    run_dir: Path
    log_file: Path
    pid_file: Path
    output_name: str = "perf.data"


@dataclass(slots=True)
class CollectConfig:
    perf_binary: str = "perf"
    event: str = "cpu-clock"
    freq: int = 49
    call_graph: str = "fp"
    segment_duration: timedelta = timedelta(minutes=1)
    retain_segments: int = 10080
    clockid: str = "CLOCK_REALTIME"
    system_wide: bool = True
    timestamp_boundary: bool = True
    extra_record_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExportConfig:
    include_comm_root: bool = True
    svg_width: int = 1600
    min_frame_width: float = 0.1


@dataclass(slots=True)
class Config:
    paths: PathsConfig
    collect: CollectConfig
    export: ExportConfig


def parse_duration(value: str | int | float | timedelta) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    text = str(value).strip().lower()
    match = _DURATION_RE.fullmatch(text)
    if not match:
        raise ValueError(f"unsupported duration: {value!r}")
    amount = float(match.group("value"))
    unit = match.group("unit") or "s"
    factor = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }[unit]
    return timedelta(seconds=amount * factor)


def _resolve_path(value: str | None, fallback: Path) -> Path:
    if not value:
        return fallback
    return Path(value)


def default_config() -> Config:
    data = tomllib.loads(DEFAULT_CONFIG_TEXT)
    return _load_from_mapping(data)


def load_config(path: str | Path) -> Config:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    return _load_from_mapping(data)


def _load_from_mapping(data: dict) -> Config:
    paths_data = dict(data.get("paths", {}))
    collect_data = dict(data.get("collect", {}))
    export_data = dict(data.get("export", {}))

    base_dir = Path(paths_data.get("base_dir", "/var/lib/perf24"))
    data_dir = _resolve_path(paths_data.get("data_dir"), base_dir / "data")
    run_dir = _resolve_path(paths_data.get("run_dir"), Path("/var/run/perf24"))
    log_file = _resolve_path(paths_data.get("log_file"), Path("/var/log/perf24/collector.log"))
    pid_file = _resolve_path(paths_data.get("pid_file"), run_dir / "perf24.pid")
    output_name = str(paths_data.get("output_name", "perf.data"))

    paths = PathsConfig(
        base_dir=base_dir,
        data_dir=data_dir,
        run_dir=run_dir,
        log_file=log_file,
        pid_file=pid_file,
        output_name=output_name,
    )

    collect = CollectConfig(
        perf_binary=str(collect_data.get("perf_binary", "perf")),
        event=str(collect_data.get("event", "cpu-clock")),
        freq=int(collect_data.get("freq", 49)),
        call_graph=str(collect_data.get("call_graph", "fp")),
        segment_duration=parse_duration(collect_data.get("segment_duration", "1m")),
        retain_segments=int(collect_data.get("retain_segments", 10080)),
        clockid=str(collect_data.get("clockid", "CLOCK_REALTIME")),
        system_wide=bool(collect_data.get("system_wide", True)),
        timestamp_boundary=bool(collect_data.get("timestamp_boundary", True)),
        extra_record_args=[str(item) for item in collect_data.get("extra_record_args", [])],
    )

    export = ExportConfig(
        include_comm_root=bool(export_data.get("include_comm_root", True)),
        svg_width=int(export_data.get("svg_width", 1600)),
        min_frame_width=float(export_data.get("min_frame_width", 0.1)),
    )

    return Config(paths=paths, collect=collect, export=export)
