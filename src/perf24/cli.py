from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import argparse
import os
import subprocess
import sys

from . import __version__
from .collector import (
    build_record_command,
    collector_status,
    ensure_directories,
    start_background,
    stop_background,
)
from .config import DEFAULT_CONFIG_TEXT, default_config, load_config, parse_duration
from .flamegraph import render_flamegraph_svg
from .query import (
    discover_segments,
    local_timezone,
    merge_stack_counters,
    parse_perf_script_stacks,
    parse_wall_clock,
    run_perf_script,
    select_segments,
    summarize_stacks,
    write_folded,
)
from .systemd import render_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="perf24", description="7x24 perf collector with flamegraph export")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="write example config and optional systemd service")
    init_parser.add_argument("--config", type=Path, required=True, help="destination config path")
    init_parser.add_argument("--force", action="store_true", help="overwrite existing files")
    init_parser.add_argument("--service-output", type=Path, help="optional systemd unit output path")
    init_parser.add_argument("--binary", default="perf24", help="binary path used in generated service")
    init_parser.set_defaults(func=cmd_init)

    start_parser = subparsers.add_parser("start", help="start background collector")
    _add_config_arg(start_parser)
    start_parser.set_defaults(func=cmd_start)

    run_parser = subparsers.add_parser("run", help="run collector in foreground")
    _add_config_arg(run_parser)
    run_parser.set_defaults(func=cmd_run)

    stop_parser = subparsers.add_parser("stop", help="stop background collector")
    _add_config_arg(stop_parser)
    stop_parser.set_defaults(func=cmd_stop)

    status_parser = subparsers.add_parser("status", help="show collector status")
    _add_config_arg(status_parser)
    status_parser.set_defaults(func=cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="validate the perf command line with --dry-run")
    _add_config_arg(doctor_parser)
    doctor_parser.set_defaults(func=cmd_doctor)

    locate_parser = subparsers.add_parser("locate", help="show slices covering a wall-clock range")
    _add_config_arg(locate_parser)
    _add_time_window_args(locate_parser)
    locate_parser.set_defaults(func=cmd_locate)

    export_parser = subparsers.add_parser("export-flamegraph", help="export a flamegraph around a wall-clock time")
    _add_config_arg(export_parser)
    _add_time_window_args(export_parser)
    export_parser.add_argument("--output", type=Path, required=True, help="output SVG path")
    export_parser.add_argument("--folded-output", type=Path, help="optional folded stack output")
    export_parser.add_argument("--comm", action="append", default=[], help="restrict to one comm, repeatable")
    export_parser.add_argument("--pid", action="append", type=int, default=[], help="restrict to one pid, repeatable")
    export_parser.set_defaults(func=cmd_export_flamegraph)

    render_parser = subparsers.add_parser("render-systemd", help="render a systemd unit")
    render_parser.add_argument("--config", type=Path, required=True, help="config path used in ExecStart")
    render_parser.add_argument("--binary", default="perf24", help="binary path used in ExecStart")
    render_parser.set_defaults(func=cmd_render_systemd)

    return parser


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True, help="TOML config path")


def _add_time_window_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--at", required=True, help="wall-clock time, for example 2026-04-27 14:23:00")
    parser.add_argument("--before", default="30s", help="time before the point, default 30s")
    parser.add_argument("--after", default="30s", help="time after the point, default 30s")


def cmd_init(args: argparse.Namespace) -> int:
    _write_file_if_allowed(args.config, DEFAULT_CONFIG_TEXT, args.force)
    if args.service_output:
        service_text = render_service(args.config, binary=args.binary)
        _write_file_if_allowed(args.service_output, service_text, args.force)
    print(f"wrote config: {args.config}")
    if args.service_output:
        print(f"wrote service: {args.service_output}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    pid = start_background(config)
    print(f"collector started with pid {pid}")
    print(f"log file: {config.paths.log_file}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    ensure_directories(config)
    command = build_record_command(config)
    print("exec:", " ".join(command))
    os.execvpe(command[0], command, os.environ | {"LC_ALL": "C", "LANG": "C"})
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    stopped = stop_background(config)
    if stopped:
        print("collector stopped")
        return 0
    print("collector was not running")
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    status = collector_status(config)
    print(f"running: {status['running']}")
    print(f"pid: {status['pid']}")
    print(f"data_dir: {status['data_dir']}")
    print(f"log_file: {status['log_file']}")
    print(f"segment_count: {status['segment_count']}")
    print(f"newest_segment: {status['newest_segment']}")
    return 0 if status["running"] else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    command = build_record_command(config, dry_run=True)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    print("command:", " ".join(command))
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def cmd_locate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    start, end = _resolve_window(args.at, args.before, args.after)
    segments = discover_segments(config)
    selected = select_segments(segments, start, end)
    print(f"query_start: {start.isoformat()}")
    print(f"query_end:   {end.isoformat()}")
    print(f"segment_count: {len(selected)}")
    for segment in selected:
        print(f"{segment.start.isoformat()} -> {segment.end.isoformat()}  {segment.path}")
    return 0 if selected else 1


def cmd_export_flamegraph(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    start, end = _resolve_window(args.at, args.before, args.after)
    segments = select_segments(discover_segments(config), start, end)
    if not segments:
        print("no perf segments cover the requested window", file=sys.stderr)
        return 2

    counters = []
    for segment in segments:
        script_output = run_perf_script(
            config=config,
            segment=segment,
            start=start,
            end=end,
            comms=args.comm or None,
            pids=args.pid or None,
        )
        counters.append(parse_perf_script_stacks(script_output, include_comm_root=config.export.include_comm_root))

    merged = merge_stack_counters(counters)
    if not merged:
        print("no samples found in the requested window", file=sys.stderr)
        return 3

    args.output.parent.mkdir(parents=True, exist_ok=True)
    title = f"perf24 flamegraph @ {parse_wall_clock(args.at, tzinfo=local_timezone()).isoformat()}"
    subtitle = f"window={args.before} before / {args.after} after, samples={sum(merged.values())}"
    svg = render_flamegraph_svg(
        merged,
        title=title,
        subtitle=subtitle,
        width=config.export.svg_width,
        min_frame_width=config.export.min_frame_width,
    )
    args.output.write_text(svg, encoding="utf-8")

    if args.folded_output:
        args.folded_output.parent.mkdir(parents=True, exist_ok=True)
        write_folded(merged, args.folded_output)

    summary_path = args.output.with_suffix(args.output.suffix + ".summary.txt")
    summary_path.write_text(summarize_stacks(merged), encoding="utf-8")

    print(f"svg: {args.output}")
    print(f"summary: {summary_path}")
    if args.folded_output:
        print(f"folded: {args.folded_output}")
    print(f"segments_used: {len(segments)}")
    return 0


def cmd_render_systemd(args: argparse.Namespace) -> int:
    print(render_service(args.config, binary=args.binary), end="")
    return 0


def _resolve_window(at_text: str, before_text: str, after_text: str) -> tuple[object, object]:
    center = parse_wall_clock(at_text, tzinfo=local_timezone())
    before = parse_duration(before_text)
    after = parse_duration(after_text)
    return center - before, center + after


def _write_file_if_allowed(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite existing file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
