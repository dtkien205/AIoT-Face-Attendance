"""Offline PAD evaluation on a consented, labeled CSV; never marks attendance.

Usage: python evaluate_pad.py --manifest /path/to/samples.csv --output report.json
Columns: path,label (live|print|replay),x,y,w,h. Boxes must match detector outputs.
"""
import argparse
import csv
import json
import math
import time
from pathlib import Path

from app.services.antispoof import AntiSpoofAdapter
from app.services.images import validate_image
from app.core.config import settings


def summarize(rows, threshold):
    live = [r for r in rows if r["label"] == "live"]
    attacks = [r for r in rows if r["label"] != "live"]
    def accepted(row):
        return row.get("real_score") is not None and row["real_score"] >= threshold
    return {
        "threshold": threshold,
        "live_samples": len(live), "attack_samples": len(attacks),
        "BPCER": sum(not accepted(r) for r in live) / len(live) if live else None,
        "APCER": sum(accepted(r) for r in attacks) / len(attacks) if attacks else None,
        "attack_acceptance_by_type": {
            label: sum(accepted(r) for r in attacks if r["label"] == label) / sum(r["label"] == label for r in attacks)
            for label in sorted({r["label"] for r in attacks})
        },
        "errors": sum(r.get("error") is not None for r in rows),
        "mean_latency_ms": sum(r["latency_ms"] for r in rows) / len(rows) if rows else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=settings.pad_real_threshold)
    args = parser.parse_args()
    if not .5 < args.threshold < 1:
        parser.error("threshold must be greater than 0.5 and less than 1")
    if args.output.exists():
        parser.error("output exists; choose a new file to preserve earlier results")
    adapter = AntiSpoofAdapter()
    if adapter.session is None:
        parser.error(adapter.reason)
    rows = []
    with args.manifest.open(newline="", encoding="utf-8-sig") as file:
        for index, entry in enumerate(csv.DictReader(file), 2):
            if entry.get("label") not in {"live", "print", "replay"}:
                parser.error(f"line {index}: label must be live, print or replay")
            start = time.perf_counter()
            row = {"sample": index - 1, "label": entry["label"], "real_score": None, "error": None}
            try:
                path = (args.manifest.parent / entry["path"]).resolve()
                if path.stat().st_size > 5 * 1024 * 1024:
                    raise ValueError("Image larger than 5 MiB")
                body = path.read_bytes()
                validate_image(body)
                box = tuple(int(entry[key]) for key in ("x", "y", "w", "h"))
                result = adapter.evaluate(body, box)
                if result.score is None or not math.isfinite(result.score):
                    raise ValueError(result.reason)
                row["real_score"] = result.score
            except (OSError, ValueError, KeyError) as exc:
                row["error"] = str(exc)
            row["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
            rows.append(row)
    if not rows:
        parser.error("manifest has no samples")
    report = {"model": adapter.model, "summary": summarize(rows, args.threshold), "samples": rows,
              "note": "Offline PAD scores only; not an end-to-end attendance or security guarantee. Use separate calibration and held-out test sets."}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
