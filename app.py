import argparse
import json
import re
import sys
from pathlib import Path
import fitz  # PyMuPDF

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

def extract_codes(pdf_path: Path):
    doc = fitz.open(pdf_path)
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

def initial_sweep(inbox: Path, recursive: bool):
    pattern = "**/*.pdf" if recursive else "*.pdf"
    out = []
    for pdf in sorted(inbox.glob(pattern)):
        try:
            out.extend(extract_codes(pdf))
        except Exception as e:
            print(f"[error] processing {pdf}: {e}", file=sys.stderr)
    return out

def main():
    ap = argparse.ArgumentParser(description="Extrai códigos verdes de PDFs com PyMuPDF.")
    ap.add_argument("--inbox", type=Path, default=Path("./inbox"))
    ap.add_argument("--recursive", action="store_true", help="processa subpastas também")
    args = ap.parse_args()
    args.inbox.mkdir(parents=True, exist_ok=True)
    print(json.dumps(initial_sweep(args.inbox, args.recursive), ensure_ascii=False))

if __name__ == "__main__":
    main()
