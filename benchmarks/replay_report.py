"""Recompute the preserved benchmark from public evidence, without model calls.

This replays the original scoring rules and observations. It does not measure
today's parser or regenerate private provider responses.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from backend.db_and_parts import CADPartFactory
from benchmarks.order_interpretation import ROOT, score, summarize

DEFAULT_ARCHIVE = ROOT / "docs/architecture/benchmark-full.json.gz"


def replay(archive=DEFAULT_ARCHIVE):
    archive = Path(archive)
    data = archive.read_bytes()
    report = json.loads(gzip.decompress(data))
    cases = {c["id"]: c for c in report["cases"]}
    rows = report["trials"]
    expected = {(case, mode, rep) for case in cases
                for mode in ("current_failover", "parallel_agreement") for rep in (1, 2, 3)}
    observed = Counter((r["case_id"], r["mode"], r["repetition"]) for r in rows)
    if (len(cases) != 20 or len(rows) != 120 or set(observed) != expected
            or any(n != 1 for n in observed.values()) or report["completed"] != len(rows)):
        raise ValueError("ERR_ARCHIVE_TRIALS: expected each case/mode/repetition exactly once")
    for row in rows:
        case = cases[row["case_id"]]
        if row["expected_action"] != case["expected_action"] or score(case, row) != row["correct"]:
            raise ValueError("ERR_ARCHIVE_SCORE: " + row["case_id"])
    # The published archive names normalized request evidence `usage`; the
    # historical summarizer calls the same records `calls`.
    summary = summarize([{**row, "calls": row["usage"]} for row in rows])
    if summary != report["summary"]:
        raise ValueError("ERR_ARCHIVE_SUMMARY: recomputed totals differ from the preserved report")
    accounting = {
        "provider_requests_including_pilot": sum(s["provider_requests"] for s in summary.values()) + len(report["pilot"]),
        "known_estimated_usd_including_pilot": round(
            sum(s["estimated_known_usd"] for s in summary.values())
            + sum(p["estimated_usd"] or 0 for p in report["pilot"]), 6),
        "requests_with_unknown_cost": sum(s["requests_without_cost_estimate"] for s in summary.values()),
    }
    if accounting != report["usage_accounting"]:
        raise ValueError("ERR_ARCHIVE_USAGE: request/cost totals differ")
    fixtures = []
    for fixture in report["fixtures"]:
        name = fixture["name"]
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("ERR_ARCHIVE_FIXTURE_PATH")
        path = archive.parent / "fixtures" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != fixture["download_sha256"]:
            raise ValueError("ERR_ARCHIVE_FIXTURE_HASH: " + name)
        poly = CADPartFactory.load_part_from_dxf(str(path))
        if (list(poly.bounds) != fixture["bounds_mm"] or abs(poly.area - fixture["area_mm2"]) > 1e-6
                or len(poly.interiors) != fixture["holes"]):
            raise ValueError("ERR_ARCHIVE_FIXTURE_GEOMETRY: " + name)
        fixtures.append(name)
    public_path = archive.with_name("benchmark.json")
    if public_path.exists():
        public = json.loads(public_path.read_text(encoding="utf-8"))
        if (public["full_evidence_archive"]["sha256"] != hashlib.sha256(data).hexdigest()
                or public["summary"] != summary):
            raise ValueError("ERR_ARCHIVE_PUBLIC_REPORT: archive and public summary disagree")
    return {"scope": "offline replay of historical observations; not a current-model benchmark",
            "baseline_commit": report["baseline_commit"], "archive_sha256": hashlib.sha256(data).hexdigest(),
            "completed": len(rows), "summary": summary, "usage_accounting": accounting,
            "verified_fixtures": fixtures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, help="Optional new JSON report; existing files are not overwritten")
    args = parser.parse_args()
    try:
        report = replay(args.archive)
        text = json.dumps(report, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(text + "\n")
        print(text)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
