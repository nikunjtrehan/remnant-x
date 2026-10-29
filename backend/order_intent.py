"""Ground supported order requirements in the customer's text before accepting a spec.

This is a bounded check for explicit parametric/DXF orders, not a general English
semantic verifier. Unclear wording must be clarified or supplied as a structured order.
"""
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from fractions import Fraction
from pathlib import Path
import re

from backend.materials import MATERIAL_SYNONYMS, normalize_material, explicit_prompt_materials

RAW_NUMBER = r"(?:\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)"
NUMBER = r"(?<![a-z0-9.])" + RAW_NUMBER
UNIT = r'(?:millimeters?|millimetres?|centimeters?|centimetres?|inches|inch|mm|cm|in|\")'
MEASURE = rf'(?P<value>{NUMBER})\s*(?P<unit>{UNIT})(?![a-z])'
WORDS = dict(zip('one two three four five six seven eight nine ten eleven twelve'.split(), range(1, 13)))
WORDS.update(a=1, an=1, single=1, dozen=12)
COUNT = r'(?:\d+|a|an|single|dozen|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)'
SHAPES = re.compile(r'\b(l[ -]?brackets?|squares?(?:\s+plates?)?|rectangular\s+plates?|rectangles?|rects?|plates?|panels?|strips?|rings?|washers?|flanges?|donuts?|circles?|discs?|disks?|pins?)\b')


def clarify(message):
    raise ValueError('ERR_ORDER_NEEDS_CLARIFICATION: ' + message)


def millimeters(match):
    try:
        value = float(Fraction(match.group('value').replace(' ', '')))
    except (ValueError, ZeroDivisionError):
        clarify('Specify a valid positive measurement.')
    unit = match.group('unit').lower()
    return value * (25.4 if unit in ('in', 'inch', 'inches', '"') else 10 if unit.startswith('c') else 1)


def quantity(prefix, context):
    match = re.search(rf'\b({COUNT})\s*(?:x\s*)?(?:(?!(?:mm|cm|inch|inches)\b)[a-z-]+\s+){{0,4}}$', prefix)
    if not match:
        match = re.search(rf'\b(?:qty|quantity)\s*(?:is|of|:|=)?\s*({COUNT})\b', context)
    if not match:
        clarify('Specify a quantity for every part, or use a structured order.')
    token = match.group(1)
    return int(token) if token.isdigit() else WORDS[token]


def dimensions(text, offset, excluded):
    found = []
    pairs = list(re.finditer(rf'(?P<value>{NUMBER})\s*(?P<first_unit>{UNIT})?\s*(?:x|×|by)\s*(?P<second>{RAW_NUMBER})\s*(?P<unit>{UNIT})(?![a-z])', text))
    for match in re.finditer(MEASURE, text):
        span = (offset + match.start(), offset + match.end())
        if not any(span[0] < end and start < span[1] for start, end in excluded) and not any(match.start() < p.end() and p.start() < match.end() for p in pairs):
            found.append((match.start(), millimeters(match)))
    # A shared trailing unit, e.g. 40 x 30 mm, specifies both dimensions.
    for match in pairs:
        span = (offset + match.start(), offset + match.end())
        if not any(span[0] < end and start < span[1] for start, end in excluded):
            first_unit = match.group('first_unit') or match.group('unit')
            first = re.fullmatch(MEASURE, match.group('value')+' '+first_unit)
            second = re.fullmatch(MEASURE, match.group('second')+' '+match.group('unit'))
            found.extend([(match.start(), millimeters(first)), (match.start('second'), millimeters(second))])
    return [value for _, value in sorted(found)]


def labelled_dimension(text, label):
    for pattern in [rf'\b(?:{label})\s*(?:diameter|diam|dia)?\s*(?:of|:|=)?\s*{MEASURE}',
                    rf'{MEASURE}\s*(?:{label})\b']:
        match = re.search(pattern, text)
        if match:
            return millimeters(match)
    return None


def inspect_order_prompt(prompt, uploads=()):
    text = prompt.lower()
    if re.search(r"\beither\b.{0,100}\bor\b|\b(?:undecided|unsure)\b|\bnot\s+(?:yet\s+)?decided\b|\b(?:do not|don't)\s+know\b|\bbetween\s+\d+\s+and\s+\d+\b|\b\d+\s+or\s+\d+\b", text, re.S):
        clarify('Resolve the alternative quantities or conflicting requirements before submitting the order.')
    if re.search(rf'[-+]\s*{MEASURE}', text):
        clarify('Specify positive unsigned part dimensions.')
    grain_locked = bool(re.search(r'\bgrain\b|\bgrain_locked\b', text) and
                        re.search(r'locked|lock|fixed|preserv|horizontal|vertical', text) and
                        not re.search(r'(?:no|without|not)\s+grain|grain_locked\s+false', text))
    thickness = []
    for pattern in [rf'\bthickness\s*(?:of|is|:|=)?\s*{MEASURE}',
                    rf'{MEASURE}\s*thick(?:ness)?\b',
                    rf'\b(?:from|on|in|use|using)\s+{MEASURE}\s+(?!(?:circles?|discs?|rings?|rectangles?|kerf)\b)[a-z]']:
        thickness.extend(re.finditer(pattern, text))
    values = {round(millimeters(m), 6) for m in thickness}
    if not values:
        clarify("Specify sheet thickness, for example 'from 3 mm SS304 sheet'.")
    if len(values) != 1:
        clarify('Specify one unambiguous sheet thickness.')
    excluded = [m.span() for m in thickness]
    kerf = re.search(rf'\bkerf\s*(?:of|is|:|=)?\s*{MEASURE}', text)
    if kerf:
        excluded.append(kerf.span())
    nodes = []
    for match in SHAPES.finditer(text):
        # "from 3 mm steel plate" names stock, not another requested part.
        if match.group() in ('plate', 'plates') and any(
            m.end() <= match.start() and re.fullmatch(r'[a-z0-9 _-]*', text[m.end():match.start()])
            for m in thickness):
            continue
        nodes.append(match)
    final = re.findall(rf'\b(?:final quantity(?:\s+is)?|change (?:the )?quantity to)\s+({COUNT})\b', text)
    if final and nodes:
        kinds = {re.sub(r's$', '', m.group()) for m in nodes}
        if len(kinds) != 1:
            clarify('Use a structured order to apply quantity corrections to multiple different parts.')
        nodes = nodes[-1:]
    parts = []
    for index, match in enumerate(nodes):
        start = 0 if index == 0 else nodes[index-1].end()
        end = nodes[index+1].start() if index+1 < len(nodes) else len(text)
        # Dimensions belong to this part after its name; the final clause may contain stock/kerf.
        context = text[match.end():end]
        dims = dimensions(context, match.end(), excluded)
        count = quantity(text[start:match.start()], context)
        if final:
            count = int(final[-1]) if final[-1].isdigit() else WORDS[final[-1]]
        name = match.group()
        shape = ('l_bracket' if name.startswith(('l-', 'l ', 'lbracket')) else
                 'ring' if name.startswith(('ring', 'washer', 'flange', 'donut')) else
                 'circle' if name.startswith(('circle', 'disc', 'disk', 'pin')) else 'rectangle')
        item = {'shape_type': shape, 'quantity': count, 'grain_locked': grain_locked}
        if shape == 'ring':
            outer = labelled_dimension(context, 'outer|outside|od')
            inner = labelled_dimension(context, 'inner|inside|id|bore')
            if outer is None or inner is None:
                clarify('Specify both outer and inner diameters for each ring.')
            if inner >= outer:
                clarify('Ring inner diameter must be smaller than its outer diameter; confirm the supplied dimensions.')
            item.update(outer_diam_mm=outer, inner_diam_mm=inner)
        elif shape == 'circle':
            if len(dims) != 1:
                clarify('Specify one diameter for each circle/disc.')
            item['diameter_mm'] = dims[0]
        else:
            required = 3 if shape == 'l_bracket' else 1 if name.startswith('square') else 2
            if len(dims) != required:
                clarify('Specify width and height, plus leg width for an L-bracket.')
            item.update(width_mm=dims[0], height_mm=dims[0] if required == 1 else dims[1])
            if shape == 'l_bracket':
                item['thickness_leg_mm'] = dims[2]
        parts.append(item)
    for path in uploads or ():
        match = re.search(re.escape(Path(path).name.lower()), text)
        if match is None and len(uploads) == 1:
            match = re.search(r'\b(?:uploaded|custom)\b', text)
        if match is None:
            continue
        parts.append({'shape_type': 'dxf_file', 'quantity': quantity(text[:match.start()], text[match.end():]),
                      'dxf_path': str(path), 'grain_locked': grain_locked})
    if not parts:
        clarify('Specify a supported part with dimensions and quantity, or bind an uploaded DXF.')
    return {'text': text, 'thickness_mm': next(iter(values)),
            'kerf_mm': millimeters(kerf) if kerf else None, 'parts': parts}


def signature(parts):
    grouped = defaultdict(int)
    for part in parts:
        shape = part['shape_type']
        fields = {'circle': ('diameter_mm',), 'ring': ('outer_diam_mm', 'inner_diam_mm'),
                  'rectangle': ('width_mm', 'height_mm'),
                  'l_bracket': ('width_mm', 'height_mm', 'thickness_leg_mm'), 'dxf_file': ('dxf_path',)}[shape]
        dims = tuple(str(Path(part[k]).resolve()).lower() if k == 'dxf_path' else round(float(part[k]), 5) for k in fields)
        if shape in ('rectangle', 'l_bracket') and not part.get('grain_locked', False):
            dims = (*sorted(dims[:2]), *dims[2:])
        grouped[(shape, dims, bool(part.get('grain_locked', False)))] += part['quantity']
    return dict(grouped)


def check_order_intent(intent, spec):
    payload = asdict(spec) if is_dataclass(spec) else spec
    if abs(payload['thickness_mm']-intent['thickness_mm']) > 1e-5:
        clarify('Interpreted sheet thickness differs from the instruction.')
    if intent['kerf_mm'] is not None and abs(payload['kerf_mm']-intent['kerf_mm']) > 1e-5:
        clarify('Interpreted kerf differs from the instruction.')
    material = normalize_material(payload['material'])
    aliases = [name for name, canonical in MATERIAL_SYNONYMS.items() if canonical == material and not name.isdigit()]
    literal = re.sub(r'[^a-z0-9]+', '_', intent['text']).strip('_')
    if material not in explicit_prompt_materials(intent['text']) and not any(re.search(r'(?<![a-z0-9])'+re.escape(name)+r'(?![a-z0-9])', intent['text']) for name in aliases) and not re.search(r'(?<![a-z0-9])'+re.escape(material)+r'(?![a-z0-9])', literal):
        clarify('Specify the material/grade explicitly; inferred material cannot be accepted.')
    if signature(intent['parts']) != signature(payload['parts']):
        clarify('Interpreted part dimensions, quantities or DXF bindings differ from the instruction.')
