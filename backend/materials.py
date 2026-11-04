"""Conservative material identities shared by order parsing and inventory.

Generic families never match a specified alloy. Unknown labels stay distinct.
"""
import re


MATERIAL_SYNONYMS = {
    "steel": "steel", "mild steel": "mild_steel", "carbon steel": "carbon_steel",
    "stainless": "stainless_steel", "stainless steel": "stainless_steel",
    "galvanized": "galvanized_steel", "galvanized steel": "galvanized_steel",
    "aluminum": "aluminum", "aluminium": "aluminum", "alu": "aluminum",
    "acrylic": "acrylic", "plexiglass": "acrylic", "perspex": "acrylic", "pmma": "acrylic",
    "cardboard": "cardboard",
    "brass": "brass", "copper": "copper", "titanium": "titanium",
    "ss304": "ss304", "ss316": "ss316", "a36": "a36",
    "6061": "al6061", "al6061": "al6061", "5052": "al5052", "al5052": "al5052",
}


def normalize_material(value: str) -> str:
    text = re.sub(r"[_-]+", " ", str(value or "").strip().lower())
    text = re.sub(r"\s+", " ", text)
    # Preserve the grade and optional temper/suffix rather than quietly dropping it.
    if text in MATERIAL_SYNONYMS:
        return MATERIAL_SYNONYMS[text]
    match = re.fullmatch(r"(?:ss\s*|stainless(?: steel)?\s*)(304l?|316l?)|(?:(304l?|316l?)\s*stainless(?: steel)?)", text)
    if match:
        return "ss" + (match.group(1) or match.group(2))
    match = re.fullmatch(r"(?:al\s*|alumin(?:um|ium)\s*)(6061|5052)", text)
    if match:
        return "al" + match.group(1)
    return text.replace(" ", "_")


def material_identity(value: str) -> dict:
    token = normalize_material(value)
    family = ("stainless_steel" if token.startswith("ss") else
              "aluminum" if token.startswith("al") else
              "steel" if token in {"steel", "mild_steel", "carbon_steel", "galvanized_steel", "a36"} else token)
    return {"material_family": family, "material_grade": token if token.startswith("ss") or token in {"al6061", "al5052", "a36"} else None}


def sheet_segmentation_concept(material: str, concept: str) -> str:
    """Resolve the legacy generic label using supplied stock identity, not vision.

    Explicit descriptions are preserved. This only changes a perception prompt;
    inventory and order matching continue to use the exact material/grade.
    """
    if concept.strip().lower() != "sheet":
        return concept
    family = material_identity(material)["material_family"]
    if family in {"steel", "mild_steel", "carbon_steel", "galvanized_steel", "stainless_steel", "aluminum", "brass", "copper", "titanium"}:
        return "metal sheet"
    return {"cardboard": "cardboard sheet", "acrylic": "acrylic sheet"}.get(family, concept)


def explicit_prompt_materials(text: str) -> set[str]:
    """Recognize explicit alloys and distinct families without interpreting quantities as alloys."""
    text = text.lower()
    grades = list(re.finditer(
        r"\b(?:ss\s*(?:304l?|316l?)|stainless(?: steel)?\s*(?:304l?|316l?)|"
        r"al\s*(?:6061|5052)|alumin(?:um|ium)\s*(?:6061|5052)|a36|"
        r"(?:6061|5052)(?=\s+(?:aluminum|aluminium|sheet|stock|plate)))"
        r"(?:[-_][a-z0-9]+)?\b", text))
    materials = {normalize_material(g.group()) for g in grades}
    family_names = sorted(
        (name for name in MATERIAL_SYNONYMS if material_identity(name)["material_grade"] is None),
        key=lambda name: (-len(name), name),
    )
    family_pattern = r"\b(?:" + "|".join(re.escape(name) for name in family_names) + r")\b"
    for family in re.finditer(family_pattern, text):
        # A grade can contain its family name ("stainless steel 304") or
        # precede it ("6061 aluminum", "SS304 steel"). Do not count that identity twice.
        family_token = normalize_material(family.group())
        family_id = material_identity(family_token)["material_family"]
        if any(g.start() < family.end() and family.start() < g.end() or
               (g.end() < family.start() and text[g.end():family.start()].isspace()
                and (material_identity(g.group())["material_family"] == family_id
                     or family_token == "steel" and material_identity(g.group())["material_family"] == "stainless_steel"))
               for g in grades):
            continue
        materials.add(family_token)
    return materials
