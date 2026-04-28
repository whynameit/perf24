from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from perf24.query import (
    Segment,
    parse_perf_script_stacks,
    parse_perf_timestamp_from_name,
    select_segments,
    write_folded,
)


class QueryTests(unittest.TestCase):
    def test_parse_perf_timestamp_from_name(self) -> None:
        tzinfo = timezone.utc
        value = parse_perf_timestamp_from_name("perf.data.20260427142300123", tzinfo=tzinfo)
        self.assertEqual(value, datetime(2026, 4, 27, 14, 23, 0, 123000, tzinfo=tzinfo))

    def test_select_segments(self) -> None:
        tzinfo = timezone.utc
        segments = [
            Segment(
                path=Path("/tmp/perf.data.1"),
                start=datetime(2026, 4, 27, 14, 20, 0, tzinfo=tzinfo),
                end=datetime(2026, 4, 27, 14, 21, 0, tzinfo=tzinfo),
            ),
            Segment(
                path=Path("/tmp/perf.data.2"),
                start=datetime(2026, 4, 27, 14, 21, 0, tzinfo=tzinfo),
                end=datetime(2026, 4, 27, 14, 22, 0, tzinfo=tzinfo),
            ),
        ]
        selected = select_segments(
            segments,
            datetime(2026, 4, 27, 14, 20, 30, tzinfo=tzinfo),
            datetime(2026, 4, 27, 14, 21, 30, tzinfo=tzinfo),
        )
        self.assertEqual([segment.path.name for segment in selected], ["perf.data.1", "perf.data.2"])

    def test_parse_perf_script_stacks(self) -> None:
        sample = """
myservice 1234/1234 [001] 1714200000.100000000: cpu-clock:
        ffffffff81000000 native_safe_halt ([kernel.kallsyms])
        7f1234567890 worker_loop (/srv/app)
        7f1234567000 main (/srv/app)

myservice 1234/1234 [001] 1714200000.200000000: cpu-clock:
        7f1234567999 do_work (/srv/app)
        7f1234567000 main (/srv/app)
"""
        stacks = parse_perf_script_stacks(sample, include_comm_root=True)
        expected = Counter(
            {
                ("[myservice]", "main", "worker_loop", "native_safe_halt"): 1,
                ("[myservice]", "main", "do_work"): 1,
            }
        )
        self.assertEqual(stacks, expected)

    def test_write_folded(self) -> None:
        target = Path("test.folded")
        try:
            write_folded(Counter({("root", "leaf"): 3}), target)
            self.assertEqual(target.read_text(encoding="utf-8"), "root;leaf 3\n")
        finally:
            target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
