from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re
import subprocess

from .collector import perf_env
from .config import Config


_STAMP_RE = re.compile(r"(?<!\d)(\d{14,20})(?!\d)")
_FRAME_RE = re.compile(r"^(?:[0-9a-fA-F]+\s+)?(.+?)(?:\s+\([^()]*\))?$")


@dataclass(slots=True)
class Segment:
    path: Path
    start: datetime
    end: datetime


def local_timezone():
    return datetime.now().astimezone().tzinfo


def parse_wall_clock(text: str, tzinfo=None) -> datetime:
    tzinfo = tzinfo or local_timezone()
    value = text.strip()

    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return datetime.fromtimestamp(float(value), tz=tzinfo)

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None

    if parsed is None:
        formats = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y%m%d%H%M%S",
            "%Y%m%d-%H%M%S",
        )
        for fmt in formats:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"unsupported timestamp: {text!r}")

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tzinfo)
    return parsed.astimezone(tzinfo)


def parse_perf_timestamp_from_name(name: str, tzinfo=None) -> datetime | None:
    tzinfo = tzinfo or local_timezone()
    matches = _STAMP_RE.findall(name)
    if not matches:
        return None
    raw = max(matches, key=len)
    main = raw[:14]
    frac = raw[14:]
    try:
        base = datetime.strptime(main, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    microseconds = int((frac + "000000")[:6]) if frac else 0
    return base.replace(microsecond=microseconds, tzinfo=tzinfo)


def discover_segments(config: Config) -> list[Segment]:
    tzinfo = local_timezone()
    candidates: list[tuple[datetime, Path]] = []
    for path in config.paths.data_dir.iterdir():
        if not path.is_file():
            continue
        if config.paths.output_name not in path.name:
            continue
        stamp = parse_perf_timestamp_from_name(path.name, tzinfo=tzinfo)
        if stamp is None:
            continue
        candidates.append((stamp, path))

    candidates.sort(key=lambda item: item[0])
    segments: list[Segment] = []
    default_duration = config.collect.segment_duration

    for index, (start, path) in enumerate(candidates):
        if index + 1 < len(candidates):
            next_start = candidates[index + 1][0]
            end = next_start if next_start > start else start + default_duration
        else:
            end = start + default_duration
        segments.append(Segment(path=path, start=start, end=end))
    return segments


def select_segments(segments: list[Segment], start: datetime, end: datetime) -> list[Segment]:
    selected = []
    for segment in segments:
        if segment.end <= start:
            continue
        if segment.start >= end:
            continue
        selected.append(segment)
    return selected


def clip_range(segment: Segment, start: datetime, end: datetime) -> tuple[datetime, datetime]:
    return max(start, segment.start), min(end, segment.end)


def to_perf_time(value: datetime) -> str:
    timestamp = value.timestamp()
    seconds = int(timestamp)
    nanos = int(round((timestamp - seconds) * 1_000_000_000))
    if nanos >= 1_000_000_000:
        seconds += 1
        nanos -= 1_000_000_000
    return f"{seconds}.{nanos:09d}"


def run_perf_script(
    config: Config,
    segment: Segment,
    start: datetime,
    end: datetime,
    comms: list[str] | None = None,
    pids: list[int] | None = None,
) -> str:
    command = [
        config.collect.perf_binary,
        "script",
        "-i",
        str(segment.path),
        "--ns",
    ]

    if config.collect.clockid.upper() == "CLOCK_REALTIME":
        clipped_start, clipped_end = clip_range(segment, start, end)
        command.extend(["--time", f"{to_perf_time(clipped_start)},{to_perf_time(clipped_end)}"])

    if comms:
        command.extend(["-c", ",".join(comms)])
    if pids:
        command.append(f"--pid={','.join(str(pid) for pid in pids)}")

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=perf_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"perf script failed for {segment.path}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def parse_perf_script_stacks(text: str, include_comm_root: bool = True) -> Counter[tuple[str, ...]]:
    stacks: Counter[tuple[str, ...]] = Counter()
    current_comm: str | None = None
    current_frames: list[str] = []

    def flush() -> None:
        nonlocal current_comm, current_frames
        if not current_frames:
            current_comm = None
            current_frames = []
            return
        stack = list(reversed(current_frames))
        if include_comm_root and current_comm:
            stack.insert(0, f"[{current_comm}]")
        stacks[tuple(stack)] += 1
        current_comm = None
        current_frames = []

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if line.startswith("#"):
            continue
        if line[:1].isspace():
            frame = _parse_frame(line)
            if frame:
                current_frames.append(frame)
            continue
        flush()
        current_comm = _parse_comm(line)

    flush()
    return stacks


def _parse_comm(header_line: str) -> str | None:
    match = re.match(r"^(?P<comm>\S+)\s+\d+(?:/\d+)?\s", header_line)
    if match:
        return match.group("comm")
    fallback = header_line.strip().split(maxsplit=1)
    return fallback[0] if fallback else None


def _parse_frame(frame_line: str) -> str | None:
    stripped = frame_line.strip()
    if not stripped or stripped in {"...", ".", ".."}:
        return None
    match = _FRAME_RE.match(stripped)
    if not match:
        return None
    frame = match.group(1).strip()
    frame = re.sub(r"\+0x[0-9a-fA-F]+$", "", frame).strip()
    return frame or None


def merge_stack_counters(counters: list[Counter[tuple[str, ...]]]) -> Counter[tuple[str, ...]]:
    merged: Counter[tuple[str, ...]] = Counter()
    for counter in counters:
        merged.update(counter)
    return merged


def write_folded(counter: Counter[tuple[str, ...]], path: Path) -> None:
    lines = [
        f"{';'.join(stack)} {count}"
        for stack, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def summarize_stacks(counter: Counter[tuple[str, ...]], limit: int = 10) -> str:
    total = sum(counter.values())
    by_root = Counter()
    by_leaf = Counter()

    for stack, count in counter.items():
        if stack:
            by_root[stack[0]] += count
            by_leaf[stack[-1]] += count

    lines = [f"total_samples={total}"]
    lines.append("top_roots:")
    for name, count in by_root.most_common(limit):
        pct = 100.0 * count / total if total else 0.0
        lines.append(f"  {pct:6.2f}% {name}")
    lines.append("top_leaf_frames:")
    for name, count in by_leaf.most_common(limit):
        pct = 100.0 * count / total if total else 0.0
        lines.append(f"  {pct:6.2f}% {name}")
    return "\n".join(lines) + "\n"
