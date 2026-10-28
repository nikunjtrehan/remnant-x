"""Explicit live SAM connectivity check; never writes inventory or exports G-code.

Run: python -m scripts.smoke_sam --synthetic
Or:  python -m scripts.smoke_sam --image station_crop.png --concept "cardboard sheet"
"""
import argparse
import json

import cv2
import numpy as np

from backend.llm_client import LiveModelClient
from backend.sam_client import segment_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true")
    source.add_argument("--image")
    parser.add_argument("--concept", default="cardboard sheet")
    parser.add_argument("--object-id")
    parser.add_argument("--box", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    args = parser.parse_args()
    if args.synthetic:
        image = np.full((480, 640, 3), 28, np.uint8)
        cv2.rectangle(image, (125, 95), (535, 395), (145, 183, 211), -1)
        cv2.circle(image, (325, 245), 48, (28, 28, 28), -1)
    else:
        image = cv2.imread(args.image)
        if image is None:
            parser.error("could not read --image")
    mask, trace = segment_image(LiveModelClient(), image, args.concept, args.object_id, args.box)
    print(json.dumps({"trace": trace, "mask_shape": list(mask.shape),
                      "foreground_pixels": int(np.count_nonzero(mask)),
                      "physical_accuracy_validated": False}, indent=2))


if __name__ == "__main__":
    main()
