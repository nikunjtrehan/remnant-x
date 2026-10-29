def emit(job):
    lines = []
    for b in job["blocks"]:
        op = b["op"]
        if op == "G21":
            lines.append("G21")
        elif op == "G90":
            lines.append("G90")
        elif op == "G94":
            lines.append("G94")
        elif op == "G17":
            lines.append("G17")
        elif op == "G91.1":
            lines.append("G91.1")
        elif op == "G00":
            lines.append(f'G00 X{b["x"]:.3f} Y{b["y"]:.3f}')
        elif op == "G01":
            lines.append(f'G01 X{b["x"]:.3f} Y{b["y"]:.3f} F{b["f"]:.1f}')
        elif op == "G02":
            lines.append(f'G02 X{b["x"]:.3f} Y{b["y"]:.3f} I{b["i"]:.3f} J{b["j"]:.3f} F{b["f"]:.1f}')
        elif op == "G03":
            lines.append(f'G03 X{b["x"]:.3f} Y{b["y"]:.3f} I{b["i"]:.3f} J{b["j"]:.3f} F{b["f"]:.1f}')
        elif op == "G04":
            lines.append(f'G04 P{b["p"]:.2f}')
        elif op == "M03":
            lines.append(f'M03 S{b["s"]:.1f}')
        elif op == "M05":
            lines.append("M05")
        elif op == "M30":
            lines.append("M02")
        else:
            lines.append(f'{b["op"]}')
    return "\n".join(lines)
