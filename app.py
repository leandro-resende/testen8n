# app.py
from flask import Flask, request, jsonify
import re
import fitz  # PyMuPDF

app = Flask(__name__)

# ====== Regras (mesmas do seu extrator enxuto) ======
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
    r"^S[A-Z0-9]+(?:\([A-Z0-9]+\))?$",
    r"^S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+(?:[ .-]S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+)*$",
    r"^T(?:E|\d)(?:\(\d+\))?$",
    r"^U\d(?:\.\d+)?(?:\(\d+\))?$",
    r"^N(?:\d+(?:\.\d+)?)?(?:\(\d+\))?$"
    r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?(?:\(\d+\))?|\(\d+\))){2,}$"
]
COMPILED = [re.compile(p) for p in PATTERNS]
_PARENS_RE = re.compile(r"\([^)]*\)")
_TOKEN_RE = re.compile(r"[A-Z0-9()\-]+")

def looks_like_code(s: str) -> bool:
    s = (s or "").strip()
    return bool(s) and any(rx.search(s) for rx in COMPILED)

def to_rgb(c):
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        r, g, b = c[:3]
        if max(r, g, b) <= 1.0:
            return (int(r * 255), int(g * 255), int(b * 255))
        return (int(r), int(g), int(b))
    return (0, 0, 0)

def is_green(rgb, g_min=110, d=20):
    r, g, b = rgb
    return (g > g_min) and (g > r + d) and (g > b + d)

def normalize_code(code: str) -> str:
    s = _PARENS_RE.sub("", code)
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"[ .\-\(]+$", "", s)

def extract_codes_from_stream(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rows, seen = [], set()
    for pno, page in enumerate(doc, 1):
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if not is_green(to_rgb(span.get("color", 0))):
                        continue
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    candidates = []
                    if looks_like_code(text):
                        candidates.append(text)
                    for tok in _TOKEN_RE.findall(text):
                        if tok not in candidates and looks_like_code(tok):
                            candidates.append(tok)
                    bbox = tuple(round(float(x), 1) for x in (span.get("bbox") or (0, 0, 0, 0)))
                    for c in candidates:
                        key = (pno, c, bbox)
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(normalize_code(c))
    doc.close()
    return rows
# ====================================================

@app.get("/")
def health():
    return "ok"

@app.post("/extract")
def extract():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="missing file field 'file'"), 400
    try:
        pdf_bytes = f.read()
        codes = extract_codes_from_stream(pdf_bytes)
        return jsonify(codes=codes)
    except Exception as e:
        return jsonify(error=str(e)), 500

# Para rodar local: gunicorn app:app -b 0.0.0.0:8000


