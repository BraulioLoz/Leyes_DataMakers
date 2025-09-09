# Limpieza de Leyes — Guía práctica y esquema JSON

Este README explica cómo convertir **documentos legales mexicanos** (limpiezas en TXT) en un **corpus JSON estructurado, estable y legible por máquina**. El flujo está diseñado para usarse desde un \*\*notebook \*\***`.ipynb`** y no requiere llamadas a APIs externas.

---

## 1) Objetivo

Generar, para cada documento limpio `clean_XXXX.txt`, un archivo `Refined/json/XXXX.json` con una estructura JSON **consistente** que preserve la jerarquía jurídica (**Capítulos/Secciones**), los **Artículos**, y sus **Fracciones**; además de metadatos como **Decreto** (preámbulo), **Título** y **Año\_publicación**.

---

## 2) Esquema JSON (contrato de datos)

El archivo escrito es `Refined/json/<base>.json` con **envoltura** de raíz `{"<base>.JSON": {...}}`.

### 2.1 Objeto raíz

```json
{
  "0001.JSON": {
    "Decreto": "Texto preambular anterior a la parte normativa...",
    "Año_publicación": 2015,
    "Título": "CONSTITUCIÓN POLÍTICA DEL ESTADO DE EJEMPLO",
    "Capítulos": [
      {
        "Capítulo": "CAPÍTULO I DE LAS DISPOSICIONES GENERALES",
        "Artículos": [
          {
            "Artículo": 1,
            "Texto": "Texto introductorio del artículo, sin fracciones...",
            "Fracciones": [
              { "Fracción": "I", "Texto": "Primera fracción..." },
              { "Fracción": "II", "Texto": "Segunda fracción..." }
            ]
          },
          {
            "Artículo": 2,
            "Texto": "Puede no tener fracciones.",
            "Fracciones": []
          }
        ]
      },
      {
        "Capítulo": "Sección segunda De la administración de bienes",
        "Artículos": [ { "Artículo": 3, "Texto": "...", "Fracciones": [] } ]
      }
    ],
    "Transitorios": [
      {
        "Capítulo": "Capítulo Único",
        "Artículos": [
          { "Artículo": "Único",  "Texto": "Vigencia...", "Fracciones": [] },
          { "Artículo": "Primero","Texto": "Medidas...", "Fracciones": [
              { "Fracción": "I", "Texto": "Primera medida..." }
          ]}
        ]
      }
    ]
  }
}
```

### 2.2 Tipos y reglas

* `Decreto`: `string` (puede ser vacío `""` si no hay preámbulo)
* `Año_publicación`: `int | null` (1850–año\_actual; si no inferible, `null`)
* `Título`: `string` (puede ser vacío, pero se aconseja detectar)
* `Capítulos`: `array` de objetos `{ Capítulo: string, Artículos: [...] }`

  * `Capítulo`: **etiqueta exacta** detectada (ej.: `"Capítulo Primero Disposiciones Generales"`, `"Sección décima segunda ..."`).
  * Si el documento **no** trae encabezados de nivel → **Capítulo Único** (fallback).
* `Artículos` (permanentes): `array` de `{ Artículo: int, Texto: string, Fracciones: [...] }`

  * `Artículo`: **número entero**. *Nota:* si el documento tiene `1`, `1 Bis`, `1 A`, aparecerán **varios objetos** con `Artículo: 1` (se distinguen por el sufijo en la fase interna, pero el JSON final mantiene entero).
  * `Texto`: todo lo que **no** pertenece a fracciones.
  * `Fracciones`: `array` de `{ Fracción: string, Texto: string }` usando **romanos** (`I, II, III, ...`).
* `Transitorios`: `array` con **un capítulo** (`Capítulo Único`), y artículos con `Artículo` = ordinal textual (`"Único"`, `"Primero"`, ...).

---

## 3) Pipeline (pasos del notebook)

1. **Rutas** y creación de carpetas.
2. **Dependencias** y **patrones** (regex) para jerarquía/encabezados/transitorios.
3. **Logger** liviano a `Refined/logs.txt`.
4. **Helpers** de normalización (acentos, espacios NBSP), detección de encabezados.
5. **Regex** de Artículos y **Fracciones** (romanos **no vacíos**; evita falsos positivos).
6. **Carga/validación** de texto limpio (`load_text`, `validate_clean_text`).
7. **Split** en `decreto` / `norma` / `trans`.
8. **Título** y **Año\_publicación** (heurísticas robustas y acento-insensibles).
9. **Artículos** y **Fracciones** (maneja fracciones “en línea”, dedup por cortes).
   10/11. **Capítulos**/**Secciones** → **JSON normativo**. Split **estricto** por *nivel* (LIBRO/TÍTULO/CAPÍTULO/SECCIÓN). **Descarta capítulos vacíos** si se configura así.
10. **Transitorios** → ordinales textuales con `Capítulo Único`.
11. **Assemble** del documento JSON.
12. **Validación Pydantic**, diagnósticos e **escritura** a disco.
13. **Batch**: procesamiento por lote y `manifest.jsonl` (+ `manifest.csv` si hay pandas).

---

## 4) Reglas de validación (Pydantic + contenido)

* Estructura debe ajustarse a modelos `LeyDoc`, `CapituloPermanente`, `ArticuloPermanente`, etc.
* **Debe existir al menos 1 artículo permanente** (`Capítulos[].Artículos[] > 0`).
* `Año_publicación` dentro de `[1850, año_actual]` si no es `null`.
* `Transitorios` puede ser `[]`.

---

## 5) Heurísticas y regex clave

* **Encabezados de nivel** (para cortar capítulos):

  * Acepta: `LIBRO`, `TÍTULO`/`TITULO`, `CAPÍTULO`/`CAPITULO`, `SECCIÓN`/`SECCION`.
  * Ordinal: romanos (`IV`), dígitos (`4`), o palabras (`Primero`, `Décima segunda`, `Único`).
  * **Excluye** `Artículo` (para no fragmentar capítulos).
* **Artículos**: `Artículo|ARTÍCULO|ART.` + número (acepta sufijos `Bis|Ter|A|B` para dedup interna).
* **Fracciones**: romanos con delimitador (`. ) — :` o **dos espacios**). **No** permiten vacío (hotfix `_ROMAN_NZ`).
* **Transitorios**: detecta encabezados `TRANSITORIOS` (incluida forma espaciada `T R A N S I T O R I O S` y `DE LOS ARTÍCULOS TRANSITORIOS`). Ordinales textuales con/sin prefijo `Artículo`.

---