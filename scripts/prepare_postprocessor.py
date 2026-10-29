"""Prepare a controller emitter with the real Muse Code CLI, outside job execution.

python -m scripts.prepare_postprocessor --profile ISO_6983_GRBL --muse path/to/muse.exe
Uses Meta API credits. The coding agent gets no tools and a disposable workspace;
generated Python must satisfy a restricted emitter contract before use.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from backend.llm_client import LiveModelClient
from backend.m3_nfp_nester import PlacedPartInstance
from backend.m4_muse_gcode import GCodeCompiler
from backend.postprocessor import PROFILES, render_emitter, program_to_job
from shapely.geometry import Polygon, box


def extract_source(output):
    candidates = []

    def inspect(value):
        if isinstance(value, dict):
            if isinstance(value.get("python_source"), str):
                candidates.append(value["python_source"])
            for child in value.values():
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str) and '"python_source"' in value:
            for index, char in enumerate(value):
                if char == "{":
                    try:
                        inspect(json.JSONDecoder().raw_decode(value[index:])[0])
                        break
                    except json.JSONDecodeError:
                        continue

    for line in output.splitlines():
        try:
            inspect(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not candidates:
        raise ValueError("ERR_MUSE_OUTPUT: structured Python source missing")
    return candidates[-1].strip() + "\n"


def validate_source(source, profile):
    compiler = GCodeCompiler()
    stock = box(0, 0, 100, 100)
    geometries = [box(10, 10, 30, 30),
                  Polygon(box(40, 40, 80, 80).exterior.coords, [box(50, 50, 60, 60).exterior.coords])]
    placed = [PlacedPartInstance(str(i), str(i), "probe", "S", 0, 0, 0, poly)
              for i, poly in enumerate(geometries)]
    compiled = compiler.compile_iso_gcode("S", stock, placed)
    emitted = render_emitter(source, program_to_job(compiled.gcode_text))
    report = compiler.verify_gcode_toolpath(emitted, stock, compiled.ordered_loops)
    if not report.verified_safe:
        raise ValueError("ERR_MUSE_PROBE: " + report.error_message)
    end = emitted.strip().splitlines()[-1].split(";", 1)[0].strip()
    expected = "M30" if profile == "ISO_6983_GRBL" else "M02"
    if end != expected:
        raise ValueError("ERR_MUSE_PROFILE_END: expected " + expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--muse", default=shutil.which("muse"))
    args = parser.parse_args()
    if not args.muse or not Path(args.muse).is_file():
        parser.error("a real installed Muse Code binary is required")
    args.muse = str(Path(args.muse).resolve())
    client = LiveModelClient()
    if not client.has_meta:
        parser.error("META_API_KEY is required")
    version = subprocess.run([args.muse, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    root = Path(__file__).resolve().parent.parent
    work_root = root / ".task-tmp" / "muse-preparation"
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_root) as workspace:
        work = Path(workspace)
        schema = {"type": "object", "properties": {"python_source": {"type": "string"}},
                  "required": ["python_source"], "additionalProperties": False}
        (work / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
        prompt = f'''Write a pure Python controller post-processor for {args.profile}.
Return only the requested JSON object with python_source. No tools or subagents.
The module must contain exactly one function: def emit(job):
It renders job["blocks"], a list of numeric motion records, to G-code text.
Records have op (G21,G90,G94,G17,G91.1,G00,G01,G02,G03,G04,M03,M05,M30).
G00 has x,y; G01 has x,y,f; G02/G03 have x,y,i,j,f; G04 has p; M03 has s.
Preserve order, coordinates, feed, power, dwell, arc direction and I/J offsets.
For GRBL emit M30 unchanged. For LINUXCNC_LASER translate M30 to M02.
Pass all other parameterless ops through unchanged. Format XY/IJ to .3f, F to
.1f, P to .2f, S to .1f. Include explicit F on each G01/G02/G03 move.
Allowed syntax ONLY: assignment to names; list literals; for loops over lists;
if/elif/else with single == or != comparisons; dictionary subscripts; literals;
f-strings without !r/!s conversions; lines.append(string); return "\\n".join(lines).
No imports, annotations, comprehensions, helper functions, len, str, int, in,
boolean operators, arithmetic, exception handling, attribute access except the
two calls above, or execution of code. Use separate branches for G02 and G03.
Start with lines = []. The final result must end in M30 (GRBL) or M02 (LinuxCNC).
This is code generation only, not machine qualification or process selection.
'''
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                                  "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"}}
        env.update({"XDG_CONFIG_HOME": str(work / "config"), "XDG_STATE_HOME": str(work / "state"),
                    "XDG_DATA_HOME": str(work / "data"), "MUSE_NO_AUTO_UPDATE": "1"})
        feedback = ""
        for attempt in range(2):
            (work / "prompt.txt").write_text(prompt + feedback, encoding="utf-8")
            command = [args.muse, "exec", "--preset", "empty", "--provider", "meta",
                       "--model", "muse-spark-1.3", "--contributor-mode", "off",
                       "--reasoning-effort", "low", "--api-key-stdin", "--json",
                       "--prompt-file", str(work / "prompt.txt"), "--output-schema", str(work / "schema.json"),
                       "--workspace", str(work), "--max-model-steps", "2", "--disable-shell",
                       "--disable-write", "--disable-web-tools", "--disable-reminders",
                       "--disable-request-user-input", "--no-foreign-personal-context", "--no-session-log"]
            completed = subprocess.run(command, input=client.meta_api_key + "\n", cwd=work,
                                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
            # Keep diagnostics private; never echo credentials or the raw session.
            (work_root / (PROFILES[args.profile] + f"-attempt-{attempt + 1}.jsonl")).write_text(
                completed.stdout, encoding="utf-8")
            (work_root / (PROFILES[args.profile] + f"-attempt-{attempt + 1}.stderr")).write_text(
                completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError("ERR_MUSE_GENERATION: CLI failed; see ignored preparation diagnostics")
            try:
                source = extract_source(completed.stdout)
                validate_source(source, args.profile)
                break
            except (ValueError, KeyError, SyntaxError, TypeError) as exc:
                if attempt == 1:
                    raise
                feedback = "\nThe deterministic check rejected the first source: " + str(exc) + ". Generate a corrected function."
        target = root / "backend" / "postprocessors"
        target.mkdir(exist_ok=True)
        manifest = {"profile": args.profile, "generator": "Muse Code", "cli_version": version,
                    "model": "muse-spark-1.3", "generated_utc": datetime.now(timezone.utc).isoformat(),
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                    "generation_attempts": attempt + 1, "probe_verified": True,
                    "physical_process_qualified": False}
        (target / (PROFILES[args.profile] + ".py")).write_text(source, encoding="utf-8")
        (target / (PROFILES[args.profile] + ".json")).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(manifest))


if __name__ == "__main__":
    main()
