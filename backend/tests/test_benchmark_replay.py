"""Recompute the published experiment without private run files or live providers."""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "docs/architecture/benchmark-full.json.gz"


def test_public_archive_reproduces_scores_usage_and_fixtures(monkeypatch):
    from benchmarks.replay_report import replay
    from backend.llm_client import LiveModelClient
    monkeypatch.setattr(LiveModelClient, "chat_completion", lambda *a, **k: pytest.fail("No live calls"))
    report = replay(ARCHIVE)
    assert report["completed"] == 120
    assert report["summary"]["current_failover"]["correct_outcomes"] == 50
    assert report["summary"]["parallel_agreement"]["correct_outcomes"] == 51
    assert report["usage_accounting"]["provider_requests_including_pilot"] == 182
    assert len(report["verified_fixtures"]) == 2


@pytest.mark.parametrize("corruption", ["score", "summary", "duplicate_trial", "fixture"])
def test_replay_rejects_inconsistent_evidence(tmp_path, corruption):
    from benchmarks.replay_report import replay
    evidence = json.loads(gzip.decompress(ARCHIVE.read_bytes()))
    if corruption == "score":
        evidence["trials"][0]["correct"] = not evidence["trials"][0]["correct"]
    elif corruption == "summary":
        evidence["summary"]["current_failover"]["correct_outcomes"] += 1
    elif corruption == "duplicate_trial":
        evidence["trials"][-1] = evidence["trials"][0]
    shutil.copytree(ARCHIVE.parent / "fixtures", tmp_path / "fixtures")
    if corruption == "fixture":
        (tmp_path / "fixtures" / evidence["fixtures"][0]["name"]).write_text("changed")
    path = tmp_path / ARCHIVE.name
    path.write_bytes(gzip.compress(json.dumps(evidence).encode()))
    with pytest.raises(ValueError, match="ERR_ARCHIVE"):
        replay(path)


def test_replay_cli_writes_only_requested_report(tmp_path):
    before = ARCHIVE.read_bytes()
    output = tmp_path / "results" / "replay.json"
    result = subprocess.run([sys.executable, "-m", "benchmarks.replay_report", "--output", str(output)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["completed"] == 120
    assert ARCHIVE.read_bytes() == before
