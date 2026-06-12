#!/usr/bin/env python3
"""
MiniTrans branded QR code generator.
Generates a styled QR code with the company logo centered on a white rounded plate.
Re-run with: .venv/bin/python3 qr_generate.py
"""

import math
import sys

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw

# Defaults; override with CLI args: qr_generate.py [url] [output.png]
URL = sys.argv[1] if len(sys.argv) > 1 else "https://minitrans.uz.ua"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "/Users/maxrosul/Projects/minitrans/minitrans-qr.png"
LOGO_PATH = "/Users/maxrosul/Projects/minitrans/assets/images/logo.png"

# Brand colour: #12346a
BRAND_BLUE = (18, 52, 106)
WHITE = (255, 255, 255)

# Logo plate: fraction of QR width to cover (width-wise).
# H error correction tolerates ~30%, so 22% is safe.
LOGO_PLATE_RATIO = 0.22

BOX_SIZE = 40
BORDER = 2
LOGO_PADDING = 24       # px of white padding around the logo inside the plate
CORNER_RADIUS = 28      # px rounding for the white plate


def make_rounded_rect(size, radius, fill):
    """Return an RGBA image of a rounded rectangle."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)],
                            radius=radius, fill=fill + (255,))
    return img


def generate_qr(logo_plate_ratio=LOGO_PLATE_RATIO):
    # ── 1. Build QR ──────────────────────────────────────────────────────────
    qr = qrcode.QRCode(
        version=None,           # auto-select
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=BOX_SIZE,
        border=BORDER,
    )
    qr.add_data(URL)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(
            front_color=BRAND_BLUE,
            back_color=WHITE,
        ),
    ).convert("RGBA")

    qr_w, qr_h = img.size
    print(f"QR base size: {qr_w}x{qr_h}px")

    # ── 2. Load & scale logo ─────────────────────────────────────────────────
    logo = Image.open(LOGO_PATH).convert("RGBA")
    logo_w, logo_h = logo.size
    logo_aspect = logo_w / logo_h

    # Plate inner width = ratio * qr_w; then add padding on both sides
    inner_w = int(logo_plate_ratio * qr_w)
    inner_h = int(inner_w / logo_aspect)

    plate_w = inner_w + 2 * LOGO_PADDING
    plate_h = inner_h + 2 * LOGO_PADDING

    logo_resized = logo.resize((inner_w, inner_h), Image.LANCZOS)

    # ── 3. Build white rounded plate ─────────────────────────────────────────
    plate = make_rounded_rect((plate_w, plate_h), CORNER_RADIUS, WHITE)
    plate.paste(logo_resized, (LOGO_PADDING, LOGO_PADDING), logo_resized)

    # ── 4. Center-paste plate onto QR ────────────────────────────────────────
    paste_x = (qr_w - plate_w) // 2
    paste_y = (qr_h - plate_h) // 2
    img.paste(plate, (paste_x, paste_y), plate)

    # ── 5. Save ──────────────────────────────────────────────────────────────
    final = img.convert("RGB")
    final.save(OUTPUT_PATH, "PNG", dpi=(300, 300))
    print(f"Saved: {OUTPUT_PATH}  ({final.size[0]}x{final.size[1]}px)")
    return final.size


def verify_qr():
    """Decode the generated QR with OpenCV and confirm the URL."""
    import cv2
    import numpy as np

    img = cv2.imread(OUTPUT_PATH)
    if img is None:
        raise FileNotFoundError(f"Cannot open {OUTPUT_PATH}")

    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(img)

    if data == URL:
        print(f"Decode OK: '{data}'")
        return True
    else:
        print(f"Decode FAILED — got: '{data}'")
        return False


if __name__ == "__main__":
    ratio = LOGO_PLATE_RATIO

    # Optional third CLI arg = custom logo plate ratio (url/output are 1st/2nd)
    if len(sys.argv) > 3:
        ratio = float(sys.argv[3])

    print(f"Generating QR with logo_plate_ratio={ratio} ...")
    size = generate_qr(logo_plate_ratio=ratio)

    ok = verify_qr()
    if not ok:
        print("\nDecoding failed — retrying with a smaller logo plate (ratio=0.18) ...")
        ratio = 0.18
        generate_qr(logo_plate_ratio=ratio)
        ok = verify_qr()
        if not ok:
            print("Still failing — retrying with ratio=0.14 ...")
            ratio = 0.14
            generate_qr(logo_plate_ratio=ratio)
            ok = verify_qr()

    if ok:
        print(f"\nFinal logo-plate ratio used: {ratio}")
        print(f"Output file: {OUTPUT_PATH}")
    else:
        print("\nERROR: QR decoding still fails after retries. "
              "Consider increasing box_size or reducing ratio further.")
        sys.exit(1)
