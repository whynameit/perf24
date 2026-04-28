from datetime import timedelta
import unittest

from perf24.collector import build_record_command
from perf24.config import default_config, parse_duration


class ConfigTests(unittest.TestCase):
    def test_parse_duration_minutes(self) -> None:
        self.assertEqual(parse_duration("90s"), timedelta(seconds=90))
        self.assertEqual(parse_duration("2m"), timedelta(minutes=2))
        self.assertEqual(parse_duration("1.5h"), timedelta(minutes=90))

    def test_build_record_command_contains_rotation_flags(self) -> None:
        config = default_config()
        command = build_record_command(config)
        self.assertIn("--switch-output", command)
        self.assertIn("--switch-max-files", command)
        self.assertIn("1m", command)
        self.assertIn("10080", command)


if __name__ == "__main__":
    unittest.main()
