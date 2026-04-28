from collections import Counter
import unittest

from perf24.flamegraph import render_flamegraph_svg


class FlamegraphTests(unittest.TestCase):
    def test_render_svg_contains_labels(self) -> None:
        stacks = Counter(
            {
                ("[svc]", "main", "worker", "leaf"): 4,
                ("[svc]", "main", "other"): 2,
            }
        )
        svg = render_flamegraph_svg(stacks, title="demo", subtitle="samples=6")
        self.assertIn("<svg", svg)
        self.assertIn("worker", svg)
        self.assertIn("demo", svg)


if __name__ == "__main__":
    unittest.main()
