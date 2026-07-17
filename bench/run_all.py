"""Run the full comparison pipeline for a region."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REGIONS
import step1_osm2gmns
import step2_overture2gmns
import step3_compare
import step4_gmns_ready
import step5_taplite
import step6_side_by_side_map


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    parser.add_argument("--skip-kernel", action="store_true")
    args = parser.parse_args()

    step1_osm2gmns.run(args.region)
    step2_overture2gmns.run(args.region)
    step3_compare.run(args.region)
    step4_gmns_ready.run(args.region)
    step5_taplite.run(args.region, skip_kernel=args.skip_kernel)
    step6_side_by_side_map.run(args.region)


if __name__ == "__main__":
    main()
