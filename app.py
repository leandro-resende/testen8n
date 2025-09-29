import os
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ------------------- Seu código (inalterado na essência) -------------------

PATTERNS = [
    r"(?i)^\d{2,3}A\s*[-/]\s*\d{1,2}kA\s*[-/]\s*\d{1,2}[HKT]$",  # 100A/10KA/1H
    r"(?i)^\d{2,3}\s*-\s*\d{1,2}kA\d{1,2}[HKT]$",               # 100-10KA1H
    r"^\d{2,3}\s*[- ]\s*\d{2,4}$",                              # 10-150, 11 300
    r"(?i)^[A-Z]{2,4}-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|\u2033)?\s*\)$",  # AM-50 (3/8")
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
    rows: List[Dict] = []

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

    # dedupe apenas repetições idênticas na MESMA posição
    uniq, seen = [], set()
    for r in rows:
        bbox = r["bbox"] or (0, 0, 0, 0)
        key = (r["page"], r["code"], tuple(round(float(x), 1) for x in bbox))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)

    doc.close()
    return uniq


_PARENS_RE = re.compile(r"\([^)]*\)")

def normalize_code(code: str) -> str:
    """
    Remove grupos entre parênteses, compacta espaços
    e limpa pontuação solta no final (espaço, ponto, hífen, parêntese).
    Exemplos: 'U3(1)' -> 'U3', 'CE1(2).CE3(1)' -> 'CE1.CE3'
    """
    s = _PARENS_RE.sub("", code)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[ .\-\(]+$", "", s)
    return s


def process_pdf(pdf_path: Path) -> List[str]:
    data = extract_green_codes_vector(pdf_path)
    return [normalize_code(d["code"]) for d in data]


def initial_sweep(inbox: Path, recursive: bool) -> List[str]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    all_codes: List[str] = []
    for pdf in sorted(inbox.glob(pattern)):
        try:
            all_codes.extend(process_pdf(pdf))
        except Exception as e:
            print(f"[error] processing {pdf}: {e}", file=sys.stderr)
    return all_codes

# ------------------- Rotas Flask -------------------

@app.get("/healthz")
def healthz():
    return "ok", 200

@app.get("/")
def root():
    return jsonify({
        "status": "ok",
        "endpoints": {
            "health": "GET /healthz",
            "upload_and_process": "POST /process (multipart form-data; campo 'files')",
            "process_inbox": "GET /process-inbox?recursive=true|false"
        }
    })

@app.post("/process")
def process_uploads():
    """
    Envie PDFs via multipart:
      files=@ex1.pdf files=@ex2.pdf
    Query:
      raw=true -> responde apenas o array JSON (compatível com seu CLI)
    """
    if "files" not in request.files:
        return jsonify({"error": "Envie pelo menos um arquivo no campo 'files'."}), 400

    codes: List[str] = []
    # usa um diretório temporário por requisição
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        for f in request.files.getlist("files"):
            if not f.filename.lower().endswith(".pdf"):
                continue
            dst = tdir / f.filename
            f.save(dst)
            codes.extend(process_pdf(dst))

    if request.args.get("raw", "").lower() in ("1", "true", "yes"):
        return Response(json.dumps(codes, ensure_ascii=False),
                        mimetype="application/json")

    return jsonify({"codes": codes, "count": len(codes)})

@app.get("/process-inbox")
def process_inbox():
    """
    Processa a pasta INBOX_DIR (padrão ./inbox).
    Query:
      recursive=true para incluir subpastas
      raw=true para devolver apenas o array JSON
    """
    recursive = request.args.get("recursive", "").lower() in ("1", "true", "yes")
    inbox_dir = Path(os.environ.get("INBOX_DIR", "./inbox"))
    inbox_dir.mkdir(parents=True, exist_ok=True)

    codes = initial_sweep(inbox_dir, recursive=recursive)

    if request.args.get("raw", "").lower() in ("1", "true", "yes"):
        return Response(json.dumps(codes, ensure_ascii=False),
                        mimetype="application/json")

    return jsonify({
        "inbox": str(inbox_dir),
        "recursive": recursive,
        "count": len(codes),
        "codes": codes
    })

# Execução local (útil para testar fora do Render)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
