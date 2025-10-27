# app.py
from flask import Flask, request, jsonify
import re
import fitz  # PyMuPDF
from typing import List, Tuple
import pandas as pd  # <-- NOVA DEPENDÊNCIA

app = Flask(__name__)

# ====== Regras (copiadas do seu script local) ======
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
]
COMPILED = [re.compile(p) for p in PATTERNS]

def looks_like_code(text: str) -> bool:
    """Verifica se o texto parece um código válido."""
    t = (text or "").strip()
    if not t:
        return False
    return any(rx.search(t) for rx in COMPILED)

def to_rgb(color_value):
    """Converte o valor de cor do span para (R, G, B)."""
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
    """Verifica se a cor RGB é verde."""
    r, g, b = rgb
    return (g > g_min) and (g > r + delta) and (g > b + delta)


def extract_codes_from_bytes(pdf_bytes: bytes) -> pd.DataFrame:
    """
    Função principal de extração, adaptada de 'extract_green_codes_vector'
    para aceitar bytes de PDF em vez de um caminho de arquivo.
    """
    # Abre o PDF a partir dos bytes recebidos
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    rows = []
    for pno, page in enumerate(doc, start=1):
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rgb = to_rgb(span.get("color", 0))
                    if not is_green(rgb):
                        continue
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    
                    # --- INÍCIO DA LÓGICA DO SCRIPT LOCAL ---
                    tokens_base = re.findall(r"[A-Z0-9()/.\\\"''\u2033-]+", text)
                    
                    tokens_split: List[str] = []
                    for t in tokens_base:
                        sub_tokens = re.split(r"(?<=\))\s*(?=[A-Z])", t)
                        tokens_split.extend(sub_tokens)

                    all_possible_tokens = set(tokens_base + tokens_split)
                    
                    raw_candidates: List[str] = []
                    if looks_like_code(text):
                        raw_candidates.append(text)
                    
                    for tok in all_possible_tokens:
                        if not tok: 
                            continue
                        
                        base_tok = re.sub(r"\([\s\d/\"'CA]+\)$", "", tok).strip()

                        if tok not in raw_candidates and looks_like_code(tok):
                            raw_candidates.append(tok)
                        
                        if base_tok and base_tok != tok and base_tok not in raw_candidates and looks_like_code(base_tok):
                            raw_candidates.append(base_tok)
                    
                    bases_found = set()
                    for cand in raw_candidates:
                        base_match = re.sub(r"\([\s\d/\"'CA]+\)$", "", cand).strip()
                        if base_match == cand and looks_like_code(cand):
                            bases_found.add(cand)

                    final_candidates = []
                    for cand in raw_candidates:
                        base_tok = re.sub(r"\([\s\d/\"'CA]+\)$", "", cand).strip()
                        
                        if base_tok != cand: 
                            if base_tok in bases_found:
                                continue
                            else:
                                final_candidates.append(cand)
                        else:
                            final_candidates.append(cand)
                    
                    candidates = sorted(list(set(final_candidates)))
                    
                    # --- FIM DA LÓGICA DO SCRIPT LOCAL ---

                    for tok in candidates:
                        rows.append({
                            # "file" é irrelevante aqui, pois não temos nome de arquivo
                            "page": pno,
                            "code": tok,
                            "span_text": text,
                            "bbox": span.get("bbox", None),
                            "rgb": rgb,
                            "method": "vector"
                        })
                        
    doc.close()

    # Deduplicação (do script local)
    uniq, seen = [], set()
    for r in rows:
        bbox = r["bbox"] or (0,0,0,0)
        key = (r["page"], r["code"], tuple(round(float(x), 1) for x in bbox))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    
    return pd.DataFrame(uniq)

# ====================================================
# --- Endpoints da API ---
# ====================================================

@app.get("/")
def health():
    return "ok"

@app.post("/extract")
def extract():
    """
    Recebe o arquivo 'file' do N8N, processa usando a nova lógica
    e retorna uma lista simples de códigos.
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="missing file field 'file'"), 400
    
    try:
        pdf_bytes = f.read()
        
        # 1. Chama a função de extração adaptada
        df_codes = extract_codes_from_bytes(pdf_bytes)
        
        # 2. Converte a coluna 'code' do DataFrame para uma lista
        codes_list = []
        if not df_codes.empty:
            # Pega apenas a coluna 'code' e converte para lista
            codes_list = df_codes["code"].tolist() 
            
        # 3. Retorna a lista de códigos, como o N8N espera
        return jsonify(codes=codes_list)
    
    except Exception as e:
        # Adiciona 'str(e)' para mais detalhes do erro no log
        return jsonify(error=f"Internal server error: {str(e)}"), 500

# (Não é necessário 'gunicorn' aqui, pois o Render usa seu próprio comando)
