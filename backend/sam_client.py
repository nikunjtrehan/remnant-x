"""SAM 3.1 Responses transport and official mask decoding (no threshold fallback)."""
import base64
import json
import re
import time

import cv2
import httpx
import numpy as np
from meta_sam_parser import CompletedOutcome, decode_mask_to_raster, image_segmentation_format


def decode_image_output(text, image_shape, object_id=None):
    height, width = image_shape[:2]
    if not text.strip():
        raise ValueError("ERR_SAM_NO_MATCH: refine the concept prompt or recapture the image")
    for rows, cols in re.findall(r";data=(\d+),(\d+),", text):
        if int(rows) * int(cols) > width * height:
            raise ValueError("ERR_SAM_MASK_SIZE")
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result
    if any(d.severity == "error" for d in result.diagnostics):
        raise ValueError("ERR_SAM_OUTPUT: malformed segmentation output")
    dimensions = re.findall(r";w=(\d+);h=(\d+)", text)
    if not dimensions or any((int(w), int(h)) != (width, height) for w, h in dimensions):
        raise ValueError(f"ERR_SAM_IMAGE_SIZE: input={width}x{height}, response dimensions={dimensions[:4]}")
    masks = [r for r in result.records if r.kind == "mask" and (object_id is None or r.object_id == str(object_id))]
    if len(masks) != 1:
        raise ValueError("ERR_SAM_OBJECT_SELECTION: require exactly one sheet; refine concept or select object_id")
    record = masks[0]
    left, top, right, bottom = (int(getattr(record.bounds, k)) for k in ("left", "top", "right", "bottom"))
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("ERR_SAM_MASK_BOUNDS")
    raster = np.frombuffer(decode_mask_to_raster(record.mask), dtype=np.uint8).reshape(record.mask.height, record.mask.width)
    raster = cv2.resize(raster, (right - left, bottom - top), interpolation=cv2.INTER_NEAREST)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[top:bottom, left:right] = raster * 255
    if not mask.any():
        raise ValueError("ERR_SAM_EMPTY_MASK")
    return mask, record.object_id


def segment_image(llm, image, concept="sheet", object_id=None, box_prompt=None):
    if not llm.has_meta:
        raise ValueError("ERR_SAM_NOT_CONFIGURED: set META_API_KEY; local_threshold must be explicitly selected for a local demo")
    if not concept.strip() or len(concept) > 200:
        raise ValueError("ERR_SAM_CONCEPT: supply a short noun phrase")
    prompt = concept
    if box_prompt is not None:
        height, width = image.shape[:2]
        if len(box_prompt) != 4 or any(type(v) is not int for v in box_prompt):
            raise ValueError("ERR_SAM_PROMPT_BOX")
        left, top, right, bottom = box_prompt
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError("ERR_SAM_PROMPT_BOX")
        # Input and parser bounds are half-open; wire boxes are inclusive.
        prompt = f"<0f>1<|box;x1={left};y1={top};x2={right-1};y2={bottom-1};w={width};h={height}|>"
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("ERR_SAM_IMAGE_ENCODING")
    payload = {
        "model": "sam-3.1", "stream": True,
        "metadata": {"mask_encoding": "one_bit"},
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")},
        ]}],
    }
    chunks, size, completed = [], 0, False
    started = time.perf_counter()
    # Disable redirects so a bearer key is never forwarded to another host.
    with httpx.Client(timeout=httpx.Timeout(120, connect=15), follow_redirects=False) as client:
        with client.stream("POST", llm.meta_base_url + "/responses", json=payload,
                           headers={"Authorization": "Bearer " + llm.meta_api_key, "Accept": "text/event-stream"}) as response:
            if response.status_code != 200:
                raise ValueError(f"ERR_SAM_HTTP: Meta returned {response.status_code}")
            data = []
            for line in response.iter_lines():
                if time.perf_counter() - started > 180:
                    raise ValueError("ERR_SAM_TIMEOUT")
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                    size += len(line)
                    if size > 20_000_000:
                        raise ValueError("ERR_SAM_RESPONSE_TOO_LARGE")
                if not line and data:
                    raw = "\n".join(data)
                    data = []
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "response.output_text.delta":
                        chunks.append(event["delta"])
                    elif kind == "response.completed":
                        completed = True
                        break
                    elif kind in {"error", "response.failed", "response.incomplete", "response.refusal.delta"}:
                        raise ValueError("ERR_SAM_RESPONSE_FAILED")
    if not completed:
        raise ValueError("ERR_SAM_INCOMPLETE_STREAM")
    mask, selected_id = decode_image_output("".join(chunks), image.shape, object_id)
    return mask, {"source": "meta_sam_3.1", "model": "sam-3.1", "object_id": selected_id,
                  "prompt_kind": "box" if box_prompt is not None else "concept",
                  "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
