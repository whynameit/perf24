from __future__ import annotations

from pathlib import Path


def render_service(config_path: str | Path, binary: str = "perf24") -> str:
    config_path = Path(config_path)
    return f"""[Unit]
Description=Continuous 7x24 perf CPU sampler
After=network.target

[Service]
Type=simple
ExecStart={binary} run --config {config_path}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
Environment=LC_ALL=C
Environment=LANG=C
WorkingDirectory=/

[Install]
WantedBy=multi-user.target
"""
