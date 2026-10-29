"""Prepared Muse Code emitters with a deliberately narrow Python contract.

Generation is offline. Only a bounded loop over typed motion records, numeric
formatting and output assembly are permitted. Uploads never supply Python code;
all emitted programs still require independent toolpath verification.
"""
import ast
from functools import lru_cache
import hashlib
import json
from pathlib import Path

PROFILES = {"ISO_6983_GRBL": "grbl", "LINUXCNC_LASER": "linuxcnc"}


@lru_cache(maxsize=8)
def validated_emitter(source):
    if len(source) > 30000:
        raise ValueError("ERR_POSTPROCESSOR_SOURCE_SIZE")
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("ERR_POSTPROCESSOR_FUNCTION")
    fn = tree.body[0]
    if (fn.name != "emit" or fn.decorator_list or fn.returns or fn.args.defaults or
        fn.args.kw_defaults or fn.args.kwonlyargs or fn.args.posonlyargs or
        fn.args.vararg or fn.args.kwarg or len(fn.args.args) != 1 or
        fn.args.args[0].arg != "job" or fn.args.args[0].annotation):
        raise ValueError("ERR_POSTPROCESSOR_SIGNATURE")
    nodes = list(ast.walk(tree))
    allowed = (ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Name,
               ast.Load, ast.Store, ast.List, ast.Constant, ast.For, ast.If, ast.Compare,
               ast.Eq, ast.NotEq, ast.JoinedStr, ast.FormattedValue, ast.Subscript,
               ast.Call, ast.Attribute, ast.Return, ast.Expr)
    if len(nodes) > 2000 or any(not isinstance(node, allowed) for node in nodes):
        raise ValueError("ERR_POSTPROCESSOR_AST")
    loops = [n for n in nodes if isinstance(n, ast.For)]
    if len(loops) != 1 or ast.unparse(loops[0].iter) != "job['blocks']" or loops[0].orelse:
        raise ValueError("ERR_POSTPROCESSOR_ITERATION")
    if not isinstance(loops[0].target, ast.Name) or loops[0].target.id in {"job", "lines"}:
        raise ValueError("ERR_POSTPROCESSOR_TARGET")
    if ast.unparse(fn.body[0]) != "lines = []":
        raise ValueError("ERR_POSTPROCESSOR_INITIALIZATION")
    call_attributes = set()
    for node in nodes:
        if isinstance(node, ast.Name) and "__" in node.id:
            raise ValueError("ERR_POSTPROCESSOR_NAME")
        if isinstance(node, ast.Assign):
            if (len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or
                node.targets[0].id == "job" or (node.targets[0].id == "lines" and node is not fn.body[0])):
                raise ValueError("ERR_POSTPROCESSOR_TARGET")
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Attribute) or node.keywords or len(node.args) != 1 or
                ast.unparse(node.func) not in {"lines.append", "'\\n'.join"}):
                raise ValueError("ERR_POSTPROCESSOR_CALL")
            call_attributes.add(id(node.func))
        if isinstance(node, ast.FormattedValue):
            if node.format_spec and not all(isinstance(p, ast.Constant) for p in node.format_spec.values):
                raise ValueError("ERR_POSTPROCESSOR_FORMAT")
            spec = ''.join(p.value for p in node.format_spec.values) if node.format_spec else ''
            if node.conversion != -1 or spec not in {"", ".1f", ".2f", ".3f", ".4f", "d"}:
                raise ValueError("ERR_POSTPROCESSOR_FORMAT")
    if any(isinstance(node, ast.Attribute) and id(node) not in call_attributes for node in nodes):
        raise ValueError("ERR_POSTPROCESSOR_ATTRIBUTE")
    namespace = {"__builtins__": {}}
    exec(compile(tree, "<prepared-postprocessor>", "exec"), namespace)
    return namespace["emit"]


def render_emitter(source, job):
    if len(job["blocks"]) > 500000:
        raise ValueError("ERR_POSTPROCESSOR_BUDGET")
    result = validated_emitter(source)(job)
    if not isinstance(result, str) or not result or len(result) > 30000000:
        raise ValueError("ERR_POSTPROCESSOR_OUTPUT")
    return result


def program_to_job(program):
    """Convert the locally planned program into numeric records, not executable code."""
    blocks, feed = [], 0.0
    for raw in program.splitlines():
        words = raw.split(";", 1)[0].split()
        if not words:
            continue
        block = {"op": words[0]}
        for word in words[1:]:
            block[word[0].lower()] = float(word[1:])
        if "f" in block:
            feed = block["f"]
        if block["op"] in {"G01", "G02", "G03"}:
            block["f"] = feed
        blocks.append(block)
    return {"blocks": blocks}


def emit_prepared(profile, program):
    if profile not in PROFILES:
        raise ValueError("ERR_UNSUPPORTED_POSTPROCESSOR")
    root = Path(__file__).parent / "postprocessors"
    try:
        source = (root / (PROFILES[profile] + ".py")).read_text(encoding="utf-8")
        manifest = json.loads((root / (PROFILES[profile] + ".json")).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("ERR_MUSE_POSTPROCESSOR_NOT_PREPARED: run scripts.prepare_postprocessor") from exc
    digest = hashlib.sha256(source.encode()).hexdigest()
    if manifest.get("source_sha256") != digest or manifest.get("profile") != profile:
        raise ValueError("ERR_POSTPROCESSOR_MANIFEST")
    return render_emitter(source, program_to_job(program)), {
        "ok": True, "provider": "muse-code-prepared", "profile": profile,
        "model": manifest.get("model"), "cli_version": manifest.get("cli_version"),
        "source_sha256": digest, "generation_is_live_per_job": False}
