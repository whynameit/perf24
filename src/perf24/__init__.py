from .query import parse_time, ensure_layout, parse_perf_script_samples
from .flamegraph import build_flame_tree, render_flamegraph_svg
from .collector import build_record_command
import collections
Counter = collections.Counter
