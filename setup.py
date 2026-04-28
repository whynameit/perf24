from setuptools import find_packages, setup
setup(
    name="perf24",
    version="0.1.0",
    description="Continuous 7x24 perf collector with time-point flamegraph export",
    package_dir={"": "src"},
    packages=find_packages("src"),
    entry_points={
        "console_scripts": [
            "perf24=perf24.cli:main",
        ]
    },
)
