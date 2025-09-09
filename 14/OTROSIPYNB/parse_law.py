# parse_law.py
"""
parse_law.py

Uso:
    python parse_law.py clean/clean_0008.txt

Requiere:
    - OPENAI_API_KEY en el entorno. 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
    - openai>=1.0.0, pydantic>=2.0.0

Este script procesa un archivo limpio de ley/decreto, extrae su estructura jurídica usando OpenAI (gpt-4.1-mini, Structured Output/Pydantic), valida y guarda el JSON en Refined/json/<base>.json, y registra logs en Refined/logs.txt.
"""

import sys
import re
import os
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI

# Modelos Pydantic
class Fraccion(BaseModel):
    Fracción: str
    Texto: str

class ArticuloPermanente(BaseModel):
    Artículo: int
    Texto: str
    Fracciones: List[Fraccion] = Field(default_factory=list)

class ArticuloTransitorio(BaseModel):
    Artículo: str   # "Único", "Primero", "Segundo", ...
    Texto: str
    Fracciones: List[Fraccion] = Field(default_factory=list)

class CapituloPermanente(BaseModel):
    Capítulo: str   # "Capítulo I" | "Capítulo Único" | etc.
    Artículos: List[ArticuloPermanente] = Field(default_factory=list)

class CapituloTransitorio(BaseModel):
    Capítulo: str
    Artículos: List[ArticuloTransitorio] = Field(default_factory=list)

class LeyDoc(BaseModel):
    Decreto: str
    Año_publicación: Optional[int] = None
    Título: str
    Capítulos: List[CapituloPermanente] = Field(default_factory=list)
    Transitorios: List[CapituloTransitorio] = Field(default_factory=list)

SYSTEM_PROMPT = """
Eres un extractor jurídico experto en legislación mexicana. Tu tarea es transformar el texto LIMPIO de una ley/decreto en un JSON ESTRICTO con el siguiente esquema (el validador usa Pydantic en el llamador):

Raíz de salida (el llamador envuelve): "<file_base>.JSON" → {objeto}
Objeto:
  - Decreto: str                      // preámbulo/preambular antes de la parte normativa; si no hay, cadena vacía
  - Año_publicación: int | null       // año más pertinente si aparece (DOF/fecha de publicación/etc.); si no, null
  - Título: str                       // nombre oficial de la ley/decreto
  - Capítulos: [                      // disposiciones permanentes (parte normativa)
      {
        "Capítulo": str,              // NOMBRE EXACTO del capítulo/sección: "Sección primera De la actuación pública", "Capítulo Primero Disposiciones Generales", etc.
        "Artículos": [
          {
            "Artículo": int,          // número arábigo
            "Texto": str,             // cuerpo del artículo SIN fracciones
            "Fracciones": [
              {"Fracción": str, "Texto": str} // fracciones con romanos conservados (I, II, III…)
            ]
          }
        ]
      }
    ]
  - Transitorios: [                   // ANIDADOS por capítulo
      {
        "Capítulo": str,              // usa "Capítulo Único" si no hay explícitos
        "Artículos": [
          {
            "Artículo": str,          // ordinal textual: "Único", "Primero", "Segundo", ...
            "Texto": str,
            "Fracciones": [
              {"Fracción": str, "Texto": str} // si existieran
            ]
          }
        ]
      }
    ]

Detección y reglas (robustas):
- Jerarquía a reconocer en encabezados (case-insensitive, acentos tolerantes):
  "disposiciones preliminares", "disposiciones generales",
  "libro", "titulo", "título", "capitulo", "capítulo", "seccion", "sección",
  "articulo", "art.", "capitulo unico", "capítulo único", "seccion unica", "sección única",
  "titulo preliminar", "título preliminar".
- Inicio de parte normativa: en la primera cabecera jerárquica real (Artículo/Título/Capítulo/Sección). Todo lo anterior es "Decreto".
- IMPORTANTE: Para el campo "Capítulo", conserva el nombre EXACTO que aparece en el texto:
  * "Capítulo Primero Disposiciones Generales"
  * "Sección primera De la actuación pública"  
  * "Sección segunda De la administración de bienes muebles e inmuebles"
  * etc.
- Si NO hay capítulos explícitos en permanentes → crear "Capítulo Único" SOLO como último recurso.
- Artículos (permanentes): encabezados del tipo "Artículo 1", "Artículo 1.", "ART. 1", "ARTÍCULO 1". El número del artículo va en entero (1, 2, 3…).
- Fracciones: detectar variantes como "I.", "I)", "I.-", "I —" (y II, III, …). Conservar romanos tal cual.
- Transitorios: encabezados tipo "TRANSITORIOS", "TRANSITORIO", "ARTÍCULOS TRANSITORIOS", "DE LOS ARTÍCULOS TRANSITORIOS" y variante espaciada "T R A N S I T O R I O S".
  * Dentro de Transitorios, los "Artículos" se marcan con ordinales textuales: "Único", "Primero", "Segundo", … (conservar textual).
  * Si no hay capítulos explícitos en transitorios, envolver en un solo capítulo "Capítulo Único".
- Normalización mínima:
  * Conservar nombres de capítulos/secciones tal cual aparecen en el texto.
  * Conservar Título oficial tal cual (con acentos/mayúsculas).
  * "Año_publicación": elegir el año más pertinente; si no aparece, null.
- Ausencias:
  * Todos los documentos deben tener artículos permanentes. Si no detectas NINGUNO, aún debes responder con JSON válido pero con "Capítulos": [] y "Transitorios": []; (el llamador registrará ERROR y no guardará JSON).
  * Si no hay "Decreto": devolver "Decreto": "" (cadena vacía).
  * Si no hay "Transitorios": devolver "Transitorios": [].
- Salida:
  * Responde con JSON puro válido (sin comentarios ni prosa).
  * La clave raíz "<file_base>.JSON" la añade el llamador (tú devuelves solo el objeto interno).
"""

BASE_DIR = Path.cwd()
OUTPUT_DIR = BASE_DIR / "Refined"
JSON_DIR = OUTPUT_DIR / "json"
LOGS_PATH = OUTPUT_DIR / "logs.txt"

def log(msg: str):
    LOGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOGS_PATH, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}] {msg}\n")

def extract_file_base(path: Path) -> str:
    m = re.search(r"(\d{3,6})", path.stem)
    return m.group(1) if m else None

def split_text_by_chapters(text: str) -> Dict[str, Any]:
    """Divide el texto en secciones: decreto, capítulos permanentes y transitorios"""
    lines = text.strip().split('\n')
    
    # Patrones para detectar estructura (más específicos para capturar secciones)
    chapter_pattern = re.compile(r'^\s*(TÍTULO|TITULO|CAPÍTULO|CAPITULO|LIBRO|SECCIÓN|SECCION|Sección|Capítulo)\s+', re.IGNORECASE)
    article_pattern = re.compile(r'^\s*(Artículo|ARTÍCULO|ART\.?)\s+\d+', re.IGNORECASE)
    transitorio_pattern = re.compile(r'^\s*(TRANSITORIOS?|ARTÍCULOS?\s+TRANSITORIOS?|DE\s+LOS\s+ARTÍCULOS?\s+TRANSITORIOS?|T\s+R\s+A\s+N\s+S\s+I\s+T\s+O\s+R\s+I\s+O\s+S)', re.IGNORECASE)
    
    # Encontrar inicio de parte normativa
    normative_start = -1
    for i, line in enumerate(lines):
        if chapter_pattern.match(line) or article_pattern.match(line):
            normative_start = i
            break
    
    # Encontrar inicio de transitorios
    transitorio_start = -1
    for i, line in enumerate(lines):
        if transitorio_pattern.match(line):
            transitorio_start = i
            break
    
    # Extraer secciones
    if normative_start == -1:
        decreto_text = '\n'.join(lines)
        normative_text = ""
        transitorio_text = ""
    else:
        decreto_text = '\n'.join(lines[:normative_start]) if normative_start > 0 else ""
        
        if transitorio_start == -1:
            normative_text = '\n'.join(lines[normative_start:])
            transitorio_text = ""
        else:
            normative_text = '\n'.join(lines[normative_start:transitorio_start])
            transitorio_text = '\n'.join(lines[transitorio_start:])
    
    # Dividir texto normativo en chunks por capítulos/títulos/secciones
    normative_chunks = []
    if normative_text.strip():
        current_chunk = []
        chunk_size_limit = 3000  # Límite de caracteres por chunk para evitar tokens excesivos
        
        for line in normative_text.split('\n'):
            # Si encontramos un nuevo capítulo/sección Y ya tenemos contenido
            if chapter_pattern.match(line) and current_chunk:
                chunk_content = '\n'.join(current_chunk)
                # Si el chunk es muy grande, dividirlo por artículos
                if len(chunk_content) > chunk_size_limit:
                    article_chunks = []
                    current_article_chunk = []
                    for chunk_line in current_chunk:
                        if article_pattern.match(chunk_line) and current_article_chunk:
                            article_chunks.append('\n'.join(current_article_chunk))
                            current_article_chunk = [chunk_line]
                        else:
                            current_article_chunk.append(chunk_line)
                    if current_article_chunk:
                        article_chunks.append('\n'.join(current_article_chunk))
                    normative_chunks.extend(article_chunks)
                else:
                    normative_chunks.append(chunk_content)
                current_chunk = [line]
            else:
                current_chunk.append(line)
        
        # Agregar el último chunk
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            if len(chunk_content) > chunk_size_limit:
                article_chunks = []
                current_article_chunk = []
                for chunk_line in current_chunk:
                    if article_pattern.match(chunk_line) and current_article_chunk:
                        article_chunks.append('\n'.join(current_article_chunk))
                        current_article_chunk = [chunk_line]
                    else:
                        current_article_chunk.append(chunk_line)
                if current_article_chunk:
                    article_chunks.append('\n'.join(current_article_chunk))
                normative_chunks.extend(article_chunks)
            else:
                normative_chunks.append(chunk_content)
    
    return {
        'decreto': decreto_text.strip(),
        'normative_chunks': normative_chunks,
        'transitorio': transitorio_text.strip()
    }

def process_chunk(client, chunk_text: str, chunk_type: str, file_base: str) -> Dict[str, Any]:
    """Procesa un chunk individual usando OpenAI"""
    
    if chunk_type == "decreto":
        prompt = f"""<file_base>={file_base}
<TEXTO_LIMPIO>
{chunk_text}
</TEXTO_LIMPIO>

Extrae únicamente:
1. Decreto: todo el texto preambular antes de la parte normativa
2. Año_publicación: año más relevante si aparece
3. Título: nombre oficial de la ley/decreto

Devuelve JSON con estas claves: {{"Decreto": "...", "Año_publicación": año_o_null, "Título": "..."}}"""
        
    elif chunk_type == "normative":
        prompt = f"""<file_base>={file_base}
<TEXTO_LIMPIO>
{chunk_text}
</TEXTO_LIMPIO>

Extrae únicamente los capítulos y artículos permanentes de este fragmento. 
IMPORTANTE: Para el campo "Capítulo", usa EXACTAMENTE el nombre completo que aparece en el texto, incluyendo:
- "Sección primera De la actuación pública"
- "Sección segunda De la administración de bienes muebles e inmuebles" 
- "Capítulo Primero Disposiciones Generales"
- etc.

NO uses "Capítulo Único" a menos que literalmente aparezca así en el texto.

Devuelve JSON con: {{"Capítulos": [...]}} siguiendo el esquema Pydantic."""
        
    elif chunk_type == "transitorio":
        prompt = f"""<file_base>={file_base}
<TEXTO_LIMPIO>
{chunk_text}
</TEXTO_LIMPIO>

Extrae únicamente los artículos transitorios de este fragmento.
Devuelve JSON con: {{"Transitorios": [...]}} siguiendo el esquema Pydantic."""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
        
    except Exception as e:
        log(f"ERROR {file_base}: fallo en chunk {chunk_type} - {e}")
        return {}

def assemble_final_json(decreto_data: Dict, normative_chunks_data: List[Dict], transitorio_data: Dict) -> Dict[str, Any]:
    """Ensambla el JSON final combinando todos los chunks"""
    
    # Estructura base
    final_doc = {
        "Decreto": decreto_data.get("Decreto", ""),
        "Año_publicación": decreto_data.get("Año_publicación"),
        "Título": decreto_data.get("Título", ""),
        "Capítulos": [],
        "Transitorios": []
    }
    
    # Combinar capítulos de todos los chunks normativos
    for chunk_data in normative_chunks_data:
        if "Capítulos" in chunk_data:
            final_doc["Capítulos"].extend(chunk_data["Capítulos"])
    
    # Agregar transitorios
    if "Transitorios" in transitorio_data:
        final_doc["Transitorios"] = transitorio_data["Transitorios"]
    
    return final_doc

def main():
    if len(sys.argv) != 2:
        print("Uso: python parse_law.py <archivo_clean.txt>")
        sys.exit(2)
    
    input_path = Path(sys.argv[1])
    if not input_path.is_file():
        print(f"ERROR: archivo no encontrado: {input_path}")
        sys.exit(2)
    
    file_base = extract_file_base(input_path)
    if not file_base:
        print("ERROR: no se pudo extraer base numérica del archivo.")
        sys.exit(2)
    
    print(f"Procesando archivo {file_base}...")
    log(f"INICIO {file_base}: iniciando procesamiento")
    
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            clean_text = f.read()
    except Exception as e:
        print(f"ERROR: fallo al leer archivo: {e}")
        sys.exit(2)

    # Dividir texto en chunks
    print(f"Dividiendo texto en secciones...")
    text_sections = split_text_by_chapters(clean_text)
    
    client = OpenAI()
    
    # Procesar decreto y metadatos
    print(f"Procesando decreto y metadatos...")
    decreto_data = {}
    if text_sections['decreto']:
        decreto_data = process_chunk(client, text_sections['decreto'], "decreto", file_base)
    
    # Procesar chunks normativos
    print(f"Procesando {len(text_sections['normative_chunks'])} capítulos normativos...")
    normative_chunks_data = []
    for i, chunk in enumerate(text_sections['normative_chunks']):
        print(f"  Procesando capítulo {i+1}/{len(text_sections['normative_chunks'])}...")
        chunk_data = process_chunk(client, chunk, "normative", file_base)
        normative_chunks_data.append(chunk_data)
    
    # Procesar transitorios
    print(f"Procesando transitorios...")
    transitorio_data = {}
    if text_sections['transitorio']:
        transitorio_data = process_chunk(client, text_sections['transitorio'], "transitorio", file_base)
    
    # Ensamblar JSON final
    print(f"Ensamblando JSON final...")
    final_doc = assemble_final_json(decreto_data, normative_chunks_data, transitorio_data)
    
    # Validar con Pydantic
    try:
        ley_doc = LeyDoc.model_validate(final_doc)
    except ValidationError as e:
        log(f"ERROR {file_base}: fallo de validación Pydantic ({e})")
        sys.exit(1)

    # Validaciones de contenido
    total_articulos = sum(len(c.Artículos) for c in ley_doc.Capítulos)
    if total_articulos == 0:
        log(f"ERROR {file_base}: no se detectaron Artículos permanentes")
        sys.exit(1)
    
    if ley_doc.Decreto.strip() == "":
        log(f"INFO {file_base}: sin Decreto")
    
    if sum(len(c.Artículos) for c in ley_doc.Transitorios) == 0:
        log(f"INFO {file_base}: sin Transitorios")

    # Escribir JSON final
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    out_path = JSON_DIR / f"{file_base}.json"
    wrapped = {f"{file_base}.JSON": ley_doc.model_dump()}
    
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(wrapped, f, indent=2, ensure_ascii=False)
        print(f"✓ JSON generado: {out_path}")
        log(f"SUCCESS {file_base}: JSON generado exitosamente - {total_articulos} artículos permanentes")
    except Exception as e:
        log(f"ERROR {file_base}: fallo al escribir JSON ({e})")
        sys.exit(1)

if __name__ == "__main__":
    main()
