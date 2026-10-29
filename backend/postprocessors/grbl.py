def emit(job):
    lines = []
    for block in job["blocks"]:
        op = block["op"]
        if op == "G00":
            x = block["x"]
            y = block["y"]
            lines.append(f"G00 X{x:.3f} Y{y:.3f}")
        elif op == "G01":
            x = block["x"]
            y = block["y"]
            f = block["f"]
            lines.append(f"G01 X{x:.3f} Y{y:.3f} F{f:.1f}")
        elif op == "G02":
            x = block["x"]
            y = block["y"]
            i = block["i"]
            j = block["j"]
            f = block["f"]
            lines.append(f"G02 X{x:.3f} Y{y:.3f} I{i:.3f} J{j:.3f} F{f:.1f}")
        elif op == "G03":
            x = block["x"]
            y = block["y"]
            i = block["i"]
            j = block["j"]
            f = block["f"]
            lines.append(f"G03 X{x:.3f} Y{y:.3f} I{i:.3f} J{j:.3f} F{f:.1f}")
        elif op == "G04":
            p = block["p"]
            lines.append(f"G04 P{p:.2f}")
        elif op == "M03":
            s = block["s"]
            lines.append(f"M03 S{s:.1f}")
        else:
            lines.append(op)
    return "\n".join(lines)
