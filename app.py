# app.py
from flask import Flask, request, jsonify
import re
import fitz  # PyMuPDF
from typing import List, Set

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
    # r"^(?:[A-Z]{1,3}\d+(?:\.\d+)?(?:\(\d+\))?){2,}$", # Redundante com o de baixo
    r"^S[A-Z0-9]+(?:\([A-Z0-9]+\))?$",
    r"^S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+(?:[ .-]S(?:[A-Z0-9]+(?:\([A-Z0-9]+\))?)+)*$",
    r"^T(?:E|\d)(?:\(\d+\))?$",
    r"^U\d(?:\.\d+)?(?:\(\d+\))?$",
    r"^N(?:\d+(?:\.\d+)?)?(?:\(\d+\))?$", # <-- VÍRGULA ADICIONADA AQUI
    r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?(?:\(\d+\))?|\(\d+\))){2,}$"
]
COMPILED = [re.compile(p) for p in PATTERNS]
_PARENS_RE = re.compile(r"\([^)]*\)")
_TOKEN_RE = re.compile(r"[A-Z0-9()/.\\\"''\u2033-]+") # Regex de token ajustado (similar ao script original)

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

# --- FUNÇÃO MODIFICADA ---
# --- FUNÇÃO MODIFICADA ---
def extract_codes_from_stream(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    rows, seen = [], set()
    
    # Regex para códigos concatenados (ex: TEU3, S1NS3R)
    # Define os "inícios" prováveis de um código (A, B, C, I, M, N, S, T, U)
    # Isso irá dividir "TEU3" em ["TE", "U3"]
    # e "S1NS3R" em ["S1N", "S3R"]
    _SPLIT_RE = re.compile(r"(?=[ABSCIMTUN])")
    
    # Regex que identifica os próprios códigos concatenados (para filtragem)
    _CONCAT_RE = re.compile(r"^(?:[A-Z]{1,3}(?:\d+(?:\.\d+)?)?(?:\(\d+\))?|\(\d+\)){2,}$")

    for pno, page in enumerate(doc, 1):
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if not is_green(to_rgb(span.get("color", 0))):
                        continue
                    text = (span.get("text") or "").strip()
                    if not text:
                        continue
                    
                    # --- INÍCIO DA ALTERAÇÃO ---
                    
                    # 1. Coleta todos os tokens possíveis
                    all_possible_tokens: Set[str] = set()
                    
                    # Adiciona o texto do span inteiro (ex: "TEU3")
                    all_possible_tokens.add(text) 
                    
                    # Adiciona tokens básicos (ex: se o texto for "TE U3", pega "TE" e "U3")
                    tokens_base = _TOKEN_RE.findall(text)
                    all_possible_tokens.update(tokens_base)

                    # 3. Divide tokens concatenados
                    # Itera sobre uma cópia para poder modificar o set
                    for t in list(all_possible_tokens): 
                        # Primeiro, divide TE(1)U3(2) -> ["TE(1)", "U3(2)"]
                        sub_tokens_parens = re.split(r"(?<=\))\s*(?=[A-Z])", t)
                        
                        for st in sub_tokens_parens:
                            # Segundo, divide TEU3 -> ["TE", "U3"]
                            # e S1NS3R -> ["S1N", "S3R"]
                            sub_tokens_split = _SPLIT_RE.split(st)
                            # Adiciona as partes (remove strings vazias do split)
                            all_possible_tokens.update(p for p in sub_tokens_split if p)

                    # 4. Valida todos os candidatos
                    raw_candidates = []
                    for tok in all_possible_tokens:
                        tok = tok.strip()
                        if tok and tok not in raw_candidates and looks_like_code(tok):
                            raw_candidates.append(tok)

                    # 5. Lógica de Preferência (Filtrar concatenados)
                    # Se encontramos 'TE', 'U3' E 'TEU3', queremos remover 'TEU3'.
                    
                    # Encontra todas as "bases" válidas (ex: 'TE', 'U3')
                    bases_found = set()
                    for cand in raw_candidates:
                        if not _CONCAT_RE.search(cand):
                            bases_found.add(cand)

                    final_candidates = []
                    for cand in raw_candidates:
                        # Se for um código concatenado (ex: 'TEU3')
                        if _CONCAT_RE.search(cand):
                            # Divide ele (ex: ['TE', 'U3'])
                            parts = [p.strip() for p in _SPLIT_RE.split(cand) if p.strip()]
                            
                            # Se TODAS as suas partes (TE, U3) tbm foram encontradas como bases...
                            if parts and all(p in bases_found for p in parts):
                                # Ignora o código 'TEU3'
                                continue 
                            else:
                                final_candidates.append(cand) # Mantém
                        else:
                            final_candidates.append(cand) # É uma base, mantém
                            
                    candidates = final_candidates
                    # --- FIM DA ALTERAÇÃO ---

                    bbox = tuple(round(float(x), 1) for x in (span.get("bbox") or (0, 0, 0, 0)))
                    for c in candidates:
                        # 'c' é o código antes da normalização (ex: "TE(1)")
                        key = (pno, c, bbox) 
                        if key in seen:
                            continue
                        seen.add(key)
                        
                        # Adiciona o código normalizado (ex: "TE")
                        rows.append(normalize_code(c)) 
                        
    doc.close()
    
    # PROBLEMA 2 CORRIGIDO: Retorna a lista 'rows' completa, sem deduplicar
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

