"""Step 4: run the gmns-ready validation toolkit on both networks.

gmns_ready scripts operate on the current working directory, so each check
runs in a subprocess chdir'ed into the network folder. Output is captured to
gmns_ready_report.txt inside each folder; failures are recorded, not fatal —
surfacing them is the point of the debugging environment.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import osm_dir, overture_dir, REGIONS

CHECKS = ("quick_check", "validate_network")


def _script_path(check: str) -> Path:
    import gmns_ready

    return Path(gmns_ready.__file__).parent / f"{check}.py"


def run_check(network_folder: Path, check: str, timeout: int = 600) -> str:
    # Run the script file directly so we can pass the target dir as argv
    # (the gmns_ready wrapper functions assume defaults like
    # 'connected_network' that don't match our layout).
    proc = subprocess.run(
        [sys.executable, str(_script_path(check)), "."],
        cwd=network_folder, capture_output=True, text=True, timeout=timeout,
    )
    return (
        f"===== gmns_ready.{check}() (exit {proc.returncode}) =====\n"
        f"{proc.stdout}\n{proc.stderr}\n"
    )


def run(region: str) -> None:
    for folder in (osm_dir(region), overture_dir(region)):
        if not (folder / "link.csv").exists():
            print(f"[step4:{region}] skipping {folder} (no link.csv)")
            continue
        chunks = []
        for check in CHECKS:
            try:
                chunks.append(run_check(folder, check))
            except subprocess.TimeoutExpired:
                chunks.append(f"===== gmns_ready.{check}() TIMED OUT =====\n")
        report = folder / "gmns_ready_report.txt"
        report.write_text("".join(chunks), encoding="utf-8", errors="replace")
        print(f"[step4:{region}] wrote {report}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    run(parser.parse_args().region)
