"""
Driver: run all Phase E plotting scripts.

Invokes each plotting module's `main()` in sequence. If one raises, we log
the error and continue so the remaining figures still get produced.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import convergence  # noqa: E402
import latent_projection  # noqa: E402
import attention_heatmap  # noqa: E402
import roc_pr_curves  # noqa: E402


PLOTS = [
    ("convergence", convergence),
    ("latent_projection", latent_projection),
    ("attention_heatmap", attention_heatmap),
    ("roc_pr_curves", roc_pr_curves),
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run every Phase E plotting script.")
    parser.add_argument("--only", nargs="+", default=None,
                        help="Only run the named modules (e.g. --only convergence roc_pr_curves)")
    args = parser.parse_args(argv)

    failures = []
    for name, mod in PLOTS:
        if args.only and name not in args.only:
            continue
        print(f"\n[run_all] === {name} ===")
        try:
            rc = mod.main([])
            if rc not in (0, None):
                failures.append((name, f"exit code {rc}"))
        except SystemExit as e:
            if e.code not in (0, None):
                failures.append((name, f"SystemExit({e.code})"))
        except Exception as e:
            failures.append((name, str(e)))
            traceback.print_exc()

    print("\n[run_all] summary:")
    if failures:
        for name, err in failures:
            print(f"  FAIL  {name}: {err}")
        return 1
    print("  all plots succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
