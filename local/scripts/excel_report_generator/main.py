import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Single config in the root .env. override=False → the CLI's own value always wins.
# parents[3] = repo root (this file lives in local/scripts/<tool>/).
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

sys.path.insert(0, str(Path(__file__).parent.parent / "notify"))
from ops import metrics_push

_REPO_TEMP = Path(__file__).parent.parent.parent / "temp"
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(_REPO_TEMP)))
MIRROR_DIR = os.getenv("MIRROR_DIR", "")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a formatted Excel file from a JSON spec")
    parser.add_argument("spec", help="JSON file with the report definition")
    parser.add_argument("--output", help="Output path for the .xlsx (overrides OUTPUT_DIR)")
    parser.add_argument("--no-copy", action="store_true", help="Don't copy to MIRROR_DIR")
    args = parser.parse_args()
    run_start = time.monotonic()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"ERROR: {spec_path} does not exist", file=sys.stderr)
        sys.exit(1)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    filename_base = spec.get("filename_base", spec_path.stem)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = OUTPUT_DIR / f"{filename_base}.xlsx"

    from generator import build_excel

    result = build_excel(spec, out_path)
    print(f"✅ Excel generated: {result}")

    if not args.no_copy and MIRROR_DIR:
        mirror = Path(MIRROR_DIR) / result.name
        try:
            shutil.copy2(result, mirror)
            print(f"📋 Copied to: {mirror}")
        except PermissionError:
            print(
                f"⚠️  No write permission on {mirror} — file available at: {result}",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"⚠️  Could not copy to {mirror}: {e}", file=sys.stderr)

    # Centralize run results in Prometheus (pushgateway → central scrape)
    metrics_push.push_run(
        "excel_report",
        duration_seconds=time.monotonic() - run_start,
        excel_report_output_bytes=float(result.stat().st_size),
    )


if __name__ == "__main__":
    main()
