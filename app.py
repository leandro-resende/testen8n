import json
import re
from pathlib import Path
from typing import List
import pandas as pd
import fitz  # PyMuPDF
try:
    import cv2
    import numpy as np
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# Patterns from your original code (unchanged)
PATTERNS = [
    r"(?i)^\d{2,3}A\s*[-/]\s*\d{1,2}kA\s*[-/]\s*\d{1,2}[HKT]$",
    r"(?i)^\d{2,3}\s*-\s*\d{1,2}kA\d{1,2}[HKT]$",
    r"^\d{2,3}\s*[- ]\s*\d{2,4}$",
    r"(?i)^[A-Z]{2,4}-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|″)?\s*\)$",
    r"(?i)^(?:AM|BM|CM)-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|″)?\s*\)\s+ABN-\d+\(\d+\)$",
    r"(?i)^ABCN-\s*\d+(?:/\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)$",
    r"(?i)^ABN(?:-\s*\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)(?:\s*\(\s*\d+\s*\))?$$",
    r"^ABN-\d+$",
    r"(?i)^AN-?\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\(\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\)$",
    r"^AN\d+\(\d+\)$",
    r"(?i)^BN-\s*\d+\s*CA{1,2}\s*\(\s*\d+\s*CA{1,2}\s*\)$",
    r"(?i)^B-\s*\d+\s*CA{1,2}$",
    r"^B\d\(\d+\)$",
    r"^B-\([A-Z0-9]+\)$",
    r"^CE\d(?:\.\d+)?(?:\(\d+\))?$$",
    r"^(?:CE\d(?:\(\d+\))?)(?:[.\-]CE\d(?:\(\d+\))?)+$",
    r"^CE(?:BE|BS|J|M)\d(?:\(\d+\))?$$",
    r"^(?:CEN\d|CM\d)(?:\(\d+\))?(?:[.\-](?:CEN\d|CM\d)(?:\(\d+\))?)+$",
    r"^CM\d(?:\(\d+\))?$$",
    r"^CM2\($",
    r"^CN(?:-\s*\d+)?\s*\(\s*\d+\s*\)$",
    r"^I\d\(\d+\)$",
    r"^M\d(?:\.\d+)?(?:\(\d+\))?$$",
    r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)(?:[ .-]{1,2}[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)+$",
    r"^(?:[A-Z]{1,3}\d+(?:\.\d+)?(?:\(\d+\))?){2,}$",
    r"^S[A-Z0-9]+(?:\([A-Z0-9]+\))?$$",
    r"^S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+(?:[ .-]S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+)*$",
    r"^T(?:E|\d)(?:\(\d+\))?$$",
    r"^U\d(?:\.\d+)?(?:\(\d+\))?$$",
    r"^N(?:\d+(?:\.\d+)?)?(?:\(\d+\))?$"
]
COMPILED = [re.compile(p) for p in PATTERNS]

def looks_like_code(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(rx.search(t) for rx in COMPILED)

def to_rgb_from_span_color(color_value):
    if isinstance(color_value, int):
        r = (color_value >> 16) & 255
        g = (color_value >> 8) & 255
        b = color_value & 255
        return (r, g, b)
    if isinstance(color_value, (list, tuple)) and len(color_value) >= 3:
        r, g, b = color_value[:3]
        if max(r, g, b) <= 1.0:
            return (int(r*255), int(g*255), int(b*255))
        return (int(r), int(g), int(b))
    return (0, 0, 0)

def is_green(rgb, g_min=110, delta=20):
    r, g, b = rgb
    return (g > g_min) and (g > r + delta) and (g > b + delta)

def extract_green_codes_vector(pdf_path: Path) -> List[str]:
    doc = fitz.open(pdf_path)
    codes = set()
    for page in doc:
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rgb = to_rgb_from_span_color(span.get("color", 0))
                    if not is_green(rgb):
                        continue
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    if looks_like_code(text):
                        codes.add(text)
                    tokens = re.findall(r"[A-Z0-9()\-]+", text)
                    for tok in tokens:
                        if looks_like_code(tok):
                            codes.add(tok)
    return sorted(codes)

def ocr_green_regions(pdf_path: Path) -> List[str]:
    if not HAS_OCR:
        return []
    codes = set()
    doc = fitz.open(pdf_path)
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2,2))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 4)[:,:,:3]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35,40,40), (95,255,255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3),np.uint8), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x,y,w,h = cv2.boundingRect(c)
            if h < 14 or w/h > 20:
                continue
            roi = img[y:y+h, x:x+w]
            txt = pytesseract.image_to_string(
                roi, config='--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789()-'
            ).strip()
            if not txt:
                continue
            if looks_like_code(txt):
                codes.add(txt)
            tokens = re.findall(r"[A-Z0-9()\-]+", txt)
            for tok in tokens:
                if looks_like_code(tok):
                    codes.add(tok)
    return sorted(codes)

def extract_green_codes(pdf_path: Path) -> List[str]:
    codes = extract_green_codes_vector(pdf_path)
    if not codes and HAS_OCR:
        codes = ocr_green_regions(pdf_path)
    return codes

# For web service (Flask)
from flask import Flask, request, jsonify
app = Flask(__name__)

@app.route('/extract', methods=['POST'])
def extract():
    if 'file' not in request.files:
        return jsonify({'error': 'No PDF file provided'}), 400
    file = request.files['file']
    pdf_path = Path('temp.pdf')
    file.save(pdf_path)
    try:
        codes = extract_green_codes(pdf_path)
        return jsonify({'codes': codes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        pdf_path.unlink(missing_ok=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)