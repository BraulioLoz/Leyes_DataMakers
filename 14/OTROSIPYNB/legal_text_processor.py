"""
Sistema para procesar textos limpios de leyes mexicanas y convertirlos a JSON estructurado.
Utiliza Pydantic para definir esquemas y validar la estructura de datos.

Autor: GitHub Copilot
Fecha: Septiembre 2025
Python: 3.11+
"""

import re
import json
import os
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ================================
# MODELOS PYDANTIC
# ================================

class Fraccion(BaseModel):
    """Modelo para representar una fracción de un artículo."""
    fraccion: str = Field(..., description="Identificador de la fracción (I, II, III, etc.)")
    texto: str = Field(..., description="Contenido textual de la fracción")

    class Config:
        str_strip_whitespace = True


class Articulo(BaseModel):
    """Modelo para representar un artículo de ley."""
    articulo: int = Field(..., description="Número del artículo")
    texto: str = Field(..., description="Contenido textual del artículo")
    fracciones: List[Fraccion] = Field(default_factory=list, description="Lista de fracciones del artículo")

    class Config:
        str_strip_whitespace = True


class Capitulo(BaseModel):
    """Modelo para representar un capítulo de ley."""
    capitulo: str = Field(..., description="Identificador del capítulo")
    articulos: List[Articulo] = Field(default_factory=list, description="Lista de artículos del capítulo")

    class Config:
        str_strip_whitespace = True


class Transitorio(BaseModel):
    """Modelo para representar un artículo transitorio."""
    articulo: str = Field(..., description="Identificador del transitorio (Primero, Segundo, etc.)")
    texto: str = Field(..., description="Contenido textual del transitorio")

    class Config:
        str_strip_whitespace = True


class LeyStructure(BaseModel):
    """Modelo principal para representar la estructura completa de una ley."""
    decreto: Optional[str] = Field(None, description="Texto del decreto que promulga la ley")
    año_publicacion: Optional[int] = Field(None, description="Año de publicación de la ley")
    titulo: str = Field(..., description="Título oficial de la ley")
    capitulos: List[Capitulo] = Field(default_factory=list, description="Lista de capítulos de la ley")
    transitorios: List[Transitorio] = Field(default_factory=list, description="Lista de artículos transitorios")

    class Config:
        str_strip_whitespace = True

    @field_validator('año_publicacion')
    @classmethod
    def validate_year(cls, v):
        """Valida que el año esté en un rango razonable."""
        if v is not None and (v < 1900 or v > 2030):
            raise ValueError('El año debe estar entre 1900 y 2030')
        return v


# ================================
# FUNCIONES DE PARSING
# ================================

class LegalTextParser:
    """Clase principal para parsear textos legales limpios."""

    def __init__(self):
        """Inicializa el parser con patrones de regex predefinidos."""
        # Patrones para identificar diferentes secciones
        self.patterns = {
            'titulo_ley': re.compile(r'^(LEY|CÓDIGO|CONSTITUCIÓN|REGLAMENTO).*?(?=TÍTULO|CAPÍTULO|Artículo|$)', re.MULTILINE | re.IGNORECASE),
            'capitulo': re.compile(r'^(TÍTULO|CAPÍTULO)\s+([IVXLCDM]+|[0-9]+|PRIMERO|SEGUNDO|TERCERO|ÚNICO).*?$', re.MULTILINE | re.IGNORECASE),
            'articulo': re.compile(r'^Artículo\s+([0-9]+º?|ÚNICO|Único)\.?\s*[-–—]?\s*(.*)', re.MULTILINE),
            'fraccion': re.compile(r'^([IVXLCDM]+|[a-z]\)|[0-9]+\))\.\s*[-–—]?\s*(.*)', re.MULTILINE),
            'transitorios': re.compile(r'^(TRANSITORIOS|ARTÍCULOS?\s+TRANSITORIOS)', re.MULTILINE | re.IGNORECASE),
            'transitorio_item': re.compile(r'^(PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|SÉPTIMO|OCTAVO|NOVENO|DÉCIMO|[0-9]+º?|[IVXLCDM]+)\.?\s*[-–—]?\s*(.*)', re.MULTILINE | re.IGNORECASE)
        }

    def limpiar_texto(self, texto: str) -> str:
        """Limpia y normaliza el texto de entrada."""
        # Eliminar espacios extra y normalizar saltos de línea
        texto = re.sub(r'\s+', ' ', texto.strip())
        # Normalizar guiones y caracteres especiales
        texto = re.sub(r'[–—]', '-', texto)
        return texto

    def extraer_decreto(self, contenido: str) -> Optional[str]:
        """Extrae el texto del decreto del inicio del documento."""
        lineas = contenido.split('\n')
        decreto_lines = []
        
        for linea in lineas:
            linea = linea.strip()
            if not linea:
                continue
                
            # Buscar patrones que indican el final del decreto
            if re.search(r'^(LEY|CÓDIGO|CONSTITUCIÓN|REGLAMENTO|TÍTULO|CAPÍTULO)', linea, re.IGNORECASE):
                break
                
            decreto_lines.append(linea)
            
            # Límite de líneas para el decreto (evitar texto muy largo)
            if len(decreto_lines) > 10:
                break
        
        if decreto_lines:
            return ' '.join(decreto_lines)
        return None

    def extraer_titulo(self, contenido: str) -> str:
        """Extrae el título de la ley del contenido."""
        lineas = contenido.split('\n')
        
        for linea in lineas:
            linea = linea.strip()
            # Buscar líneas que contengan LEY, CÓDIGO, CONSTITUCIÓN, etc.
            if re.search(r'^(LEY|CÓDIGO|CONSTITUCIÓN|REGLAMENTO)', linea, re.IGNORECASE):
                # Limpiar el título
                titulo = re.sub(r'^(LEY\s+DE\s+INGRESOS\s+DEL\s+|LEY\s+)', '', linea, flags=re.IGNORECASE)
                return self.limpiar_texto(titulo)
        
        # Si no encuentra un patrón específico, usar la primera línea que parece un título
        for linea in lineas[:10]:  # Revisar solo las primeras 10 líneas
            linea = linea.strip()
            if len(linea) > 10 and linea.isupper():
                return self.limpiar_texto(linea)
        
        return "Título no identificado"

    def parsear_fracciones(self, texto: str) -> List[Fraccion]:
        """Parsea las fracciones de un artículo."""
        fracciones = []
        lines = texto.split('\n')
        current_fraccion = None
        current_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Buscar inicio de nueva fracción
            match = self.patterns['fraccion'].match(line)
            if match:
                # Guardar fracción anterior si existe
                if current_fraccion and current_text:
                    fracciones.append(Fraccion(
                        fraccion=current_fraccion,
                        texto=self.limpiar_texto(' '.join(current_text))
                    ))
                
                # Iniciar nueva fracción
                current_fraccion = match.group(1).rstrip('.')
                current_text = [match.group(2)] if match.group(2) else []
            elif current_fraccion:
                # Continuar texto de fracción actual
                current_text.append(line)
        
        # Guardar última fracción
        if current_fraccion and current_text:
            fracciones.append(Fraccion(
                fraccion=current_fraccion,
                texto=self.limpiar_texto(' '.join(current_text))
            ))
        
        return fracciones

    def parsear_articulos(self, contenido: str, inicio: int, fin: int) -> List[Articulo]:
        """Parsea los artículos de una sección del texto."""
        articulos = []
        lines = contenido.split('\n')[inicio:fin]
        current_articulo = None
        current_text = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Verificar si es un nuevo capítulo/título (para evitar mezclas)
            if self.patterns['capitulo'].match(line):
                break
                
            # Buscar inicio de nuevo artículo
            match = self.patterns['articulo'].match(line)
            if match:
                # Guardar artículo anterior si existe
                if current_articulo is not None and current_text:
                    texto_completo = '\n'.join(current_text)
                    fracciones = self.parsear_fracciones(texto_completo)
                    
                    # Si hay fracciones, el texto del artículo es solo hasta la primera fracción
                    if fracciones:
                        first_fraction_line = None
                        for i, text_line in enumerate(current_text):
                            if self.patterns['fraccion'].match(text_line.strip()):
                                first_fraction_line = i
                                break
                        if first_fraction_line is not None:
                            texto_articulo = ' '.join(current_text[:first_fraction_line])
                        else:
                            texto_articulo = ' '.join(current_text)
                    else:
                        texto_articulo = ' '.join(current_text)
                    
                    articulos.append(Articulo(
                        articulo=current_articulo,
                        texto=self.limpiar_texto(texto_articulo),
                        fracciones=fracciones
                    ))
                
                # Iniciar nuevo artículo
                articulo_num_str = match.group(1).replace('º', '').replace('°', '')
                try:
                    current_articulo = int(articulo_num_str) if articulo_num_str.isdigit() else 1
                except:
                    current_articulo = 1
                
                current_text = [match.group(2)] if match.group(2) else []
            elif current_articulo is not None:
                # Verificar si la línea es parte de un nuevo capítulo o título
                if self.patterns['capitulo'].match(line):
                    break
                # Continuar texto del artículo actual
                current_text.append(line)
        
        # Guardar último artículo
        if current_articulo is not None and current_text:
            texto_completo = '\n'.join(current_text)
            fracciones = self.parsear_fracciones(texto_completo)
            
            if fracciones:
                first_fraction_line = None
                for i, text_line in enumerate(current_text):
                    if self.patterns['fraccion'].match(text_line.strip()):
                        first_fraction_line = i
                        break
                if first_fraction_line is not None:
                    texto_articulo = ' '.join(current_text[:first_fraction_line])
                else:
                    texto_articulo = ' '.join(current_text)
            else:
                texto_articulo = ' '.join(current_text)
            
            articulos.append(Articulo(
                articulo=current_articulo,
                texto=self.limpiar_texto(texto_articulo),
                fracciones=fracciones
            ))
        
        return articulos

    def parsear_capitulos(self, contenido: str) -> List[Capitulo]:
        """Parsea todos los capítulos del contenido."""
        capitulos = []
        lines = contenido.split('\n')
        
        # Encontrar todas las posiciones de capítulos
        capitulo_positions = []
        for i, line in enumerate(lines):
            if self.patterns['capitulo'].match(line.strip()):
                capitulo_positions.append((i, line.strip()))
        
        # Si no hay capítulos explícitos, crear uno general
        if not capitulo_positions:
            articulos = self.parsear_articulos(contenido, 0, len(lines))
            if articulos:
                capitulos.append(Capitulo(
                    capitulo="CAPÍTULO ÚNICO",
                    articulos=articulos
                ))
            return capitulos
        
        # Parsear cada capítulo
        for i, (pos, titulo) in enumerate(capitulo_positions):
            # Determinar fin del capítulo (siguiente capítulo o transitorios)
            fin_pos = len(lines)
            
            # Buscar siguiente capítulo
            if i + 1 < len(capitulo_positions):
                fin_pos = capitulo_positions[i + 1][0]
            
            # Buscar transitorios para delimitar mejor (solo si es el último capítulo)
            if i == len(capitulo_positions) - 1:
                for j in range(pos, len(lines)):
                    if self.patterns['transitorios'].match(lines[j].strip()):
                        fin_pos = j
                        break
            
            # Parsear artículos del capítulo, comenzando después del título del capítulo
            articulos = self.parsear_articulos(contenido, pos + 1, fin_pos)
            
            if articulos:  # Solo agregar capítulos con artículos
                capitulos.append(Capitulo(
                    capitulo=titulo,
                    articulos=articulos
                ))
        
        return capitulos

    def parsear_transitorios(self, contenido: str) -> List[Transitorio]:
        """Parsea los artículos transitorios del contenido."""
        transitorios = []
        lines = contenido.split('\n')
        
        # Encontrar inicio de sección de transitorios
        inicio_transitorios = None
        for i, line in enumerate(lines):
            if self.patterns['transitorios'].match(line.strip()):
                inicio_transitorios = i
                break
        
        if inicio_transitorios is None:
            return transitorios
        
        # Parsear cada transitorio
        current_transitorio = None
        current_text = []
        
        for line in lines[inicio_transitorios + 1:]:
            line = line.strip()
            if not line:
                continue
            
            # Buscar inicio de nuevo transitorio
            match = self.patterns['transitorio_item'].match(line)
            if match:
                # Guardar transitorio anterior si existe
                if current_transitorio and current_text:
                    transitorios.append(Transitorio(
                        articulo=current_transitorio,
                        texto=self.limpiar_texto(' '.join(current_text))
                    ))
                
                # Iniciar nuevo transitorio
                current_transitorio = match.group(1).rstrip('.')
                current_text = [match.group(2)] if match.group(2) else []
            elif current_transitorio:
                # Continuar texto del transitorio actual
                current_text.append(line)
        
        # Guardar último transitorio
        if current_transitorio and current_text:
            transitorios.append(Transitorio(
                articulo=current_transitorio,
                texto=self.limpiar_texto(' '.join(current_text))
            ))
        
        return transitorios

    def procesar_archivo(self, archivo_path: str) -> LeyStructure:
        """Procesa un archivo de texto limpio y retorna la estructura de ley."""
        print(f"Procesando archivo: {archivo_path}")
        
        # Leer contenido del archivo
        try:
            with open(archivo_path, 'r', encoding='utf-8') as file:
                contenido = file.read()
        except UnicodeDecodeError:
            # Intentar con diferentes codificaciones
            try:
                with open(archivo_path, 'r', encoding='latin-1') as file:
                    contenido = file.read()
            except:
                with open(archivo_path, 'r', encoding='cp1252') as file:
                    contenido = file.read()
        
        # Extraer componentes
        decreto = self.extraer_decreto(contenido)
        titulo = self.extraer_titulo(contenido)
        capitulos = self.parsear_capitulos(contenido)
        transitorios = self.parsear_transitorios(contenido)
        
        # Mostrar advertencias
        if not decreto:
            print(f"⚠️  ADVERTENCIA: No se encontró decreto en {archivo_path}")
        
        if not capitulos:
            print(f"⚠️  ADVERTENCIA: No se encontraron capítulos en {archivo_path}")
        
        if not transitorios:
            print(f"⚠️  ADVERTENCIA: No se encontraron transitorios en {archivo_path}")
        
        # Crear estructura
        return LeyStructure(
            decreto=decreto,
            titulo=titulo,
            capitulos=capitulos,
            transitorios=transitorios
        )

    def deducir_año_openai(self, contenido: str) -> Optional[int]:
        """
        Hook para integrar OpenAI y deducir el año de publicación.
        Por ahora retorna None, se puede implementar después.
        """
        # TODO: Implementar llamada a OpenAI para deducir año
        # Buscar patrones de fecha en el texto
        import datetime
        current_year = datetime.datetime.now().year
        
        # Buscar años en el texto (patrón simple)
        years = re.findall(r'\b(19[0-9]{2}|20[0-2][0-9])\b', contenido)
        if years:
            # Retornar el año más reciente que no sea futuro
            valid_years = [int(y) for y in years if int(y) <= current_year]
            if valid_years:
                return max(valid_years)
        
        return None


# ================================
# FUNCIÓN PRINCIPAL DE PROCESAMIENTO
# ================================

def procesar_directorio_clean(directorio_base: str, archivo_especifico: Optional[str] = None):
    """
    Procesa todos los archivos clean_*.txt de un directorio y genera archivos JSON.
    
    Args:
        directorio_base: Ruta al directorio que contiene la carpeta temp/clean/
        archivo_especifico: Si se especifica, solo procesa este archivo
    """
    parser = LegalTextParser()
    
    # Configurar rutas
    clean_dir = Path(directorio_base) / "temp" / "clean"
    json_dir = Path(directorio_base) / "Refined" / "json"
    
    # Crear directorio de salida si no existe
    json_dir.mkdir(parents=True, exist_ok=True)
    
    # Obtener lista de archivos a procesar
    if archivo_especifico:
        archivos = [clean_dir / archivo_especifico]
    else:
        archivos = list(clean_dir.glob("clean_*.txt"))
    
    print(f"Encontrados {len(archivos)} archivos para procesar")
    
    # Procesar cada archivo
    for archivo_path in sorted(archivos):
        if not archivo_path.exists():
            print(f"❌ Archivo no encontrado: {archivo_path}")
            continue
        
        try:
            # Procesar archivo
            ley_structure = parser.procesar_archivo(str(archivo_path))
            
            # Intentar deducir año si no está presente
            if ley_structure.año_publicacion is None:
                with open(archivo_path, 'r', encoding='utf-8') as f:
                    contenido = f.read()
                año = parser.deducir_año_openai(contenido)
                if año:
                    ley_structure.año_publicacion = año
            
            # Generar nombre de archivo JSON
            base_name = archivo_path.stem.replace("clean_", "")
            json_filename = f"{base_name}.json"
            json_path = json_dir / json_filename
            
            # Crear estructura final con clave
            output_data = {
                json_filename: ley_structure.model_dump()
            }
            
            # Escribir archivo JSON
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            print(f"✅ Procesado exitosamente: {archivo_path.name} -> {json_filename}")
            print(f"   📊 Capítulos: {len(ley_structure.capitulos)}")
            total_articulos = sum(len(cap.articulos) for cap in ley_structure.capitulos)
            print(f"   📊 Artículos: {total_articulos}")
            print(f"   📊 Transitorios: {len(ley_structure.transitorios)}")
            
        except Exception as e:
            print(f"❌ Error procesando {archivo_path.name}: {str(e)}")
            continue


# ================================
# FUNCIÓN DE EJEMPLO Y TESTING
# ================================

def test_single_file():
    """Función para probar un archivo específico."""
    directorio_base = r"c:\Users\braul\Documents\_ITAMLaptop\Datalab\DataMakers\Leyes\14"
    print("🚀 Iniciando procesamiento de prueba (archivo 0001)...")
    procesar_directorio_clean(directorio_base, "clean_0001.txt")
    print("\n✨ Procesamiento de prueba completado!")


def main():
    """Función principal para testing del sistema."""
    # Directorio base (ajustar según sea necesario)
    directorio_base = r"c:\Users\braul\Documents\_ITAMLaptop\Datalab\DataMakers\Leyes\14"
    
    # Procesar todos los archivos
    print("🚀 Iniciando procesamiento de textos legales...")
    procesar_directorio_clean(directorio_base)
    
    print("\n✨ Procesamiento completado!")


if __name__ == "__main__":
    main()
