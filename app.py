import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, Tuple, Optional, List

import fitz

PATTERNS = [
    r"(?i)^\d{2,3}A\s*[-/]\s*\d{1,2}kA\s*[-/]\s*\d{1,2}[HKT]$",
    # ex.: 100A/10KA/1H, 100A-10kA-8T, 40A-2KA-8K

    # 2) Variante compacta sem "A" no 1º bloco
    r"(?i)^\d{2,3}\s*-\s*\d{1,2}kA\d{1,2}[HKT]$",
    # ex.: 100-10KA1H

    # 3) Apenas números com hífen ou espaço
    r"^\d{2,3}\s*[- ]\s*\d{2,4}$",
    # ex.: 10-150, 11 300, 12-1000

    # 4) Prefixos (2–4 letras) + número + fração em polegadas
    r"(?i)^[A-Z]{2,4}-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|\u2033)?\s*\)$",
    # ex.: AM-50 (3/8"), BM-50(3/8"), ABCM-150 (3/8"), CM-50(3/8)

    # 5) Linha com dois códigos (fração + ABN)
    r"(?i)^(?:AM|BM|CM)-\d+\s*\(\s*\d+/\d+\s*(?:\"|''|\u2033)?\s*\)\s+ABN-\d+\(\d+\)$",
    # ex.: AM-50 (3/8") ABN-70(70)

    # 6) ABCN com variações de CA e frações
    r"(?i)^ABCN-\s*\d+(?:/\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)$",
    # ex.: ABCN-1/0 CA (2 CA), ABCN-120(70), ABCN-2CA(4CA)

    # 7) ABN com (opcional "-número"), CA e 1 ou 2 parênteses
    r"(?i)^ABN(?:-\s*\d+)?\s*(?:CA)?\s*\(\s*\d+(?:/\d+)?\s*(?:CA)?\s*\)(?:\s*\(\s*\d+\s*\))?$",
    # ex.: ABN(16), ABN(16)(16), ABN-2 CA(2 CA), ABN-70(70)

    # 8) ABN simples com hífen e número
    r"^ABN-\d+$",
    # ex.: ABN-7

    # 9) AN com/sem hífen, CA/CAA e frações
    r"(?i)^AN-?\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\(\s*\d+(?:/\d+)?\s*(?:CA{1,2})?\s*\)$",
    # ex.: AN-10(10), AN-4 CA(4 CA), AN-4CAA(4)

    # 10) AN compacto número(parênteses)
    r"^AN\d+\(\d+\)$",
    # ex.: AN16(16)

    # 11) BN com CA/CAA nos dois lados
    r"(?i)^BN-\s*\d+\s*CA{1,2}\s*\(\s*\d+\s*CA{1,2}\s*\)$",
    # ex.: BN-4CA(4CA)

    # 12) B com CA/CAA
    r"(?i)^B-\s*\d+\s*CA{1,2}$",
    # ex.: B-2 CA, B-2 CAA

    # 13) B seguido de número(parênteses)
    r"^B\d\(\d+\)$",
    # ex.: B1(1), B2(1), BE1(1), CE1(1) (vide regras CE abaixo)

    # 14) B com conteúdo alfanumérico entre parênteses
    r"^B-\([A-Z0-9]+\)$",
    # ex.: B-(1N5)

    # 15) CE simples (com opcional .x e/ou (n))
    r"^CE\d(?:\.\d+)?(?:\(\d+\))?$",
    # ex.: CE2, CE2.3, CE4(1)

    # 16) Cadeias só de CE com "." ou "-"
    r"^(?:CE\d(?:\(\d+\))?)(?:[.\-]CE\d(?:\(\d+\))?)+$",
    # ex.: CE3.CE3, CE3-CE3(1), CE4(1)-CE3(2)

    # 17) Prefixos especiais CE: CEBE/CEBS/CEJ/CEM
    r"^CE(?:BE|BS|J|M)\d(?:\(\d+\))?$",
    # ex.: CEBE1(1), CEBS3, CEJ2(1), CEM4(1)

    # 18) CEN/CM encadeados com "." ou "-"
    r"^(?:CEN\d|CM\d)(?:\(\d+\))?(?:[.\-](?:CEN\d|CM\d)(?:\(\d+\))?)+$",
    # ex.: CEN3.CM3-CEN3, CM3-CM3, CM3-CM3(1)

    # 19) CM simples (e caso com parêntese aberto)
    r"^CM\d(?:\(\d+\))?$",
    # ex.: CM1, CM3(2), CM4(1)
    r"^CM2\($",
    # ex.: CM2(

    # 20) CN com opcional "-número" e (n)
    r"^CN(?:-\s*\d+)?\s*\(\s*\d+\s*\)$",
    # ex.: CN(10), CN-16 (16), CN-10(10)

    # 21) I seguido de número(parênteses)
    r"^I\d\(\d+\)$",
    # ex.: I3(1)

    # 22) M simples (com opcional .x e/ou (n))
    r"^M\d(?:\.\d+)?(?:\(\d+\))?$",
    # ex.: M1, M2.3, M4(1)

    # 23) Cadeias gerais de “etiquetas” (1–3 letras) separadas por espaço/hífen/ponto
    r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)(?:[ .-]{1,2}[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?)+$",
    # ex.: M1(2) N2(1), N1-U3, N3-N4, U4(1) U3(2), U3.N(2), N1(1) U3(1)

    # 24) Etiquetas justapostas (sem separador), 2+ blocos letra(s)+número(s)
    r"^(?:[A-Z]{1,3}\d+(?:\.\d+)?(?:\(\d+\))?){2,}$",
    # ex.: U2U3, U1(1)U3(2), U3(1)CM3(1), U3(2)CE2(1)

    # 25) Família “S…” (um ou várias, com concatenação, espaço, ponto ou hífen)
    r"^S[A-Z0-9]+(?:\([A-Z0-9]+\))?$",
    # ex.: S1N, SI3, S3R(BT), SI4R
    r"^S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+(?:[ .-]S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+)*$",
    # ex.: S1N S3R, S3N.SI3, S3R-SI1-SI3, S1NS3R, S4RS3N.S3R, S32F.SI3, S43N3N

    # 26) T/TE com (n) opcional
    r"^T(?:E|\d)(?:\(\d+\))?$",
    # ex.: TE, TE(1), T4(1)

    # 27) U e N isolados (com .x e/ou (n) opcionais)
    r"^U\d(?:\.\d+)?(?:\(\d+\))?$",
    # ex.: U1, U3.2(1), U4(2)
    r"^N(?:\d+(?:\.\d+)?)?(?:\(\d+\))?$"
    # ex.: N(1), N3, N3.2, N4(1)

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

def process_pdf(pdf_path: Path) -> List[str]:
    data = extract_green_codes_vector(pdf_path)
    if not data:
        print(f"[info] {pdf_path.name}: Nenhum código verde encontrado.")
        return []
    codes = sorted(set(d['code'] for d in data))
    print(f"[ok] {pdf_path.name}: {len(codes)} código(s) encontrado(s):")
    for code in codes:
        print(f" - {code}")
    return codes

def initial_sweep(inbox: Path, recursive: bool):
    pattern = "**/*.pdf" if recursive else "*.pdf"
    all_codes = {}
    for pdf in sorted(inbox.glob(pattern)):
        try:
            codes = process_pdf(pdf)
            all_codes[str(pdf)] = codes
        except Exception as e:
            print(f"[error] processing {pdf}: {e}")
    if all_codes:
        print("\nResumo de todos os códigos verdes:")
        print(json.dumps(all_codes, indent=2, ensure_ascii=False))
    else:
        print("\nNenhum PDF processado ou nenhum código encontrado.")

def main():
    ap = argparse.ArgumentParser(description="Extrai códigos verdes de PDFs usando apenas PyMuPDF.")
    ap.add_argument("--inbox", type=Path, default=Path("./inbox"))
    ap.add_argument("--recursive", action="store_true", help="processa subpastas também")
    args = ap.parse_args()

    args.inbox.mkdir(parents=True, exist_ok=True)

    initial_sweep(args.inbox, recursive=args.recursive)

if __name__ == "__main__":
    main()
