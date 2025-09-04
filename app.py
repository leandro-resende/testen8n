from flask import Flask, request, jsonify
import os
import tempfile
import re
from pathlib import Path
from typing import List, Dict
import fitz

app = Flask(__name__)

PATTERNS = [
    r"(?i)^\d{2,3}A\s*[-/]\s*\d{1,2}kA\s*[-/]\s*\d{1,2}[HKT]$",
    r"(?i)^\d{2,3}\s*-\s*\d{1,2}kA\d{1,2}[HKT]$",
    r"^\d{2,3}\s*[- ]\s*\d{2,4}$",
    r"(?i)^[A-Z]{2,4}-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|\u2033)?\s*\)$",
    r"(?i)^(?:AM|BM|CM)-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|\u2033)?\s*\)\s+ABN-\d+\(\d+\)$",
    r"(?i)^ABCN-\s*\d+(?:/\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)$",
    r"(?i)^ABN(?:-\s*\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)(?:\s*\(\s*\d+\s*\))?$",
    r"^ABN-\d+$",
    r"(?i)^AN-?\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\(\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\)$",
    r"^AN\d+\(\d+\)$",
    r"(?i)^BN-\s*\d+\s*CA{1,2}\s*\(\s*\d+\s*CA{1,2}\s*\)$",
    r"(?i)^B-\s*\d+\s*CA{1,2}$",
    r"^B\d\(\d+\)$",
    r"^B-\([A-Z0-9]+\)$",
    r"^CE\d(?:\.\d+)?(?:\(\d+\))?$",
    r"^(?:CE\d(?:\(\d+\))?)(?:[.\-]CE\d(?:\(\d+\))?)+$",
    r"^CE(?:BE|BS|J|M)\d(?:\(\d+\))?$",
    r"^(?:CEN\d|CM\d)(?:\(\d+\))?(?:[.\-](?:CEN\d|CM\d)(?:\(\d+\))?)+$",
    r"^CM\d(?:\(\d+\))?$",
    r"^CM2\($",
    r"^CN(?:-\s*\d+)?\s*\(\s*\d+\s*\)$",
    r"^I\d\(\d+\)$",
    r"^M\d(?:\.\d+)?(?:\(\d+\))?$",
    r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)(?:[ .-]{1,2}[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)+$",
    r"^(?:[A-Z]{1,3}\d+(?:\.\d+)?(?:\(\d+\))?){2,}$",
    r"^S[A-Z0-9]+(?:\([A-Z0-9]+\))?$",
    r"^S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+(?:[ .-]S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+)*$",
    r"^T(?:E|\d)(?:\(\d+\))?$",
    r"^U\d(?:\.\d+)?(?:\(\d+\))?$",
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

def extract_green_codes_vector(pdf_path: Path) -> List[Dict]:
    doc = fitz.open(pdf_path)
    rows = []
    for pno, page in enumerate(doc, start=1):
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
                    tokens = re.findall(r"[A-Z0-9()\-]+", text)
                    candidates: List[str] = []
                    if looks_like_code(text):
                        candidates.append(text)
                    for tok in tokens:
                        if tok not in candidates and looks_like_code(tok):
                            candidates.append(tok)
                    for tok in candidates:
                        rows.append({
                            "file": pdf_path.name,
                            "page": pno,
                            "code": tok,
                            "span_text": text,
                            "bbox": span.get("bbox", None),
                            "rgb": rgb,
                            "method": "vector"
                        })
    uniq, seen = [], set()
    for r in rows:
        bbox = r["bbox"] or (0,0,0,0)
        key = (r["page"], r["code"], tuple(round(float(x), 1) for x in bbox))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    doc.close()
    return uniq

@app.route('/extract', methods=['POST'])
def extract_codes():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and file.filename.lower().endswith('.pdf'):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / file.filename
            file.save(pdf_path)
            data = extract_green_codes_vector(pdf_path)
            if not data:
                return jsonify({'codes': []})
            codes = sorted(set(d['code'] for d in data))
            return jsonify({'codes': codes})
    return jsonify({'error': 'Invalid file'}), 400

if __name__ == '__main__':
    app.run(debug=True)
