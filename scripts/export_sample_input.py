"""Export only a public case's input object for POST /optimize-energy."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", nargs="?", default="SAMPLE-01")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output", type=Path, default=Path("sample-input.json"))
    args = parser.parse_args()

    with args.samples.open(encoding="utf-8") as source:
        payload = json.load(source)
    cases = payload["cases"] if isinstance(payload, dict) else payload
    matching = [case for case in cases if case.get("id") == args.case_id]
    if len(matching) != 1:
        parser.error(f"Expected exactly one case with id {args.case_id!r}")

    request = matching[0]["input"]
    args.output.write_text(json.dumps(request, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.case_id} request to {args.output.resolve()}")


if __name__ == "__main__":
    main()
