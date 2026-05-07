# Tablero Indicadores INEGI

Dashboard web permanente para consulta rápida de 33 indicadores económicos oficiales INEGI. HTML estático generado desde JSON por indicador, pipeline Python, Chart.js 4.4.1 para gráficas cliente. Stakeholders: banca de desarrollo, gobierno federal. Datos públicos.

No es reporte puntual. Es dashboard siempre disponible. Las prioridades son existencia, frescura, tiempo de carga. No agregar contenido one-off.

## Estado

V1 funcional. 33 JSON poblados, build reproducible, validador automatizado diario, 0 errors en baseline. Ingesta vía Reporte mensual (PPT Presidencia INEGI) + XLSX de datos embebidos. Deploy pendiente.

## Arquitectura

```
indicadores_inegi/
├── assets/
│   ├── app.js              # filtros de tabla, render Chart.js
│   └── styles.css          # paleta GobMx 2024-2030 (chrome) + PPT institucional (charts)
├── cache/
│   └── inegi.ics           # calendario oficial INEGI cacheado
├── config/
│   ├── calendar.json       # próximas publicaciones por indicador
│   ├── headline_cards.json # tarjetas destacadas en vista general
│   ├── indicators.json     # catálogo maestro de los 33 indicadores
│   ├── ppt_mapping.json    # mapping slide del Reporte mensual → indicador local
│   └── thresholds.json     # umbrales verde/amarillo/rojo
├── data/
│   ├── <indicador>.json    # 33 archivos, uno por indicador
│   ├── catalog.json        # metadata global
│   └── interpretations.json
├── logs/
├── scripts/
│   ├── build.py            # orquestador: JSON → site/
│   ├── normalize.py        # helpers shared entre build y herramientas
│   ├── validate.py         # validador 5 capas post-build
│   ├── ingest_pptx.py      # ingesta desde Reporte mensual .pptx
│   ├── calendar_sync.py    # sincroniza calendar.json desde ICS INEGI
│   └── requirements.txt
├── templates/
│   ├── base.html.j2
│   ├── index.html.j2       # vista general
│   └── indicador.html.j2   # ficha por indicador
├── site/                   # output del build
└── README.md
```

## Flujo mensual

La fuente de verdad es el Reporte mensual de indicadores económicos que produce Presidencia del INEGI, junto con su XLSX de datos embebidos. Llegan cada mes con datos consolidados. 29 indicadores corresponden al bloque principal del reporte, 4 adicionales (ENOE mensual, PIB estatal, ITAEE estatal, IMAI estatal) se extraen del anexo XLSX porque tienen hoja pero no bloque narrativo dedicado en la PPT.

```bash
cd indicadores_inegi

# 1. Ingesta. Regenera data/<indicador>.json desde la PPT
python3 scripts/ingest_pptx.py /ruta/Reporte-YYYY-MM.pptx

# 2. Build. Regenera site/ con los JSON actualizados
python3 scripts/build.py

# 3. Validate. QA en 5 capas
python3 scripts/validate.py
```

Opciones útiles:

```bash
python3 scripts/ingest_pptx.py <pptx> --indicator inpc_mensual  # un solo indicador
python3 scripts/ingest_pptx.py <pptx> --dry-run                 # preview sin escribir
python3 scripts/validate.py --severity info                     # incluye info
```

El mapping slide → indicador vive en `config/ppt_mapping.json`. Agregar un indicador nuevo al pipeline consiste en registrar su entrada ahí con `slide_index`, `title_contains`, `column_map` alineado a `columnas_normalizadas` del JSON destino.

Campos regenerados por la ingesta: `periodos`, `series`, `ultima_actualizacion`, `benchmarks.ma12_<campo>`. Campos preservados: metadata (nombre, categoría, fuente, unidades), `alertas_activas`, `_productos` y `_entidades_ciudades` (estos últimos vienen del boletín PDF del INEGI, no del PPT).

## Indicadores cubiertos

33 indicadores en 6 bloques:

- Actividad. IGAE, IOAE, PIB trimestral, PIB anual, PIB por actividad, PIB participación, actividad industrial, ind_ciclicos
- Precios. INPC mensual, INPC quincenal, INPP, inflación_resumen
- Mercado laboral. ENOE trimestral, ENOE mensual
- Comercio y servicios. Balanza comercial, exportaciones por entidad, autos ligeros, autos pesados, EMIM, ENEC, comercio mayoreo, comercio menudeo, servicios, consumo privado, FBCF
- Regional. PIB estatal, ITAEE estatal, IMAI estatal
- Confianza y expectativas. Confianza consumidor, EMOE IAT, EMOE ICE, EMOE IPM

5 tienen umbrales calibrados en `thresholds.json`: INPC, IGAE, exportaciones, confianza consumidor, desocupación ENOE. Los 28 restantes están en neutro (calibración pendiente).

Estado de ingesta desde PPT (abril 2026): `inpc_mensual` validado vía `ingest_pptx.py` con merge PPT + XLSX embebido. Los 4 regionales/mensual (`enoe_mensual`, `pib_estatal`, `itaee_estatal`, `imai_estatal`) se pueblan con `seed_new_indicators.py` porque dependen solo del XLSX. Los 28 restantes del bloque principal siguen el patrón INPC pero requieren entrada en `ppt_mapping.json`.

## Paleta

Chrome del site usa paleta GobMx 2024-2030 (`#9B2247` guinda primario, `#1E5B4F` verde secundario). Gráficas Chart.js usan paleta PPT institucional (`#08989C`, `#9F2578`, `#003057`). Separación deliberada: el chrome comunica oficialidad, las gráficas comunican datos.

## Validador

5 capas: schema de JSONs, campos obligatorios, consistencia JSON vs HTML, normalización numérica cross-page, detección de series degeneradas. Scheduled task `validate-indicadores-inegi` cron `0 8 * * 1-5`.

Baseline actual: 0 errors · 0 warnings · 1 info (`ioae` tiene solo 1 punto válido, esperado).

## Instalación

```bash
cd indicadores_inegi
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Requisitos: Python 3.10+, `python-pptx`, `Jinja2`, `beautifulsoup4`.

## Fuentes

- Reporte mensual de indicadores económicos, Presidencia del INEGI (PPT mensual, fuente principal)
- Boletines individuales del INEGI para bloques especiales (INPC productos/entidades/ciudades). Ver `config/indicators.json` campo `boletin_url`
- Calendario oficial INEGI: `https://www.inegi.org.mx/contenidos/saladeprensa/doc/inegi.ics`

## Pendientes

1. Deploy. Definir hospedaje (GitHub Pages si datos públicos sin restricción institucional, bucket interno si compliance lo exige). Bloquea que el tablero exista para sus usuarios.
2. Accesibilidad WCAG 2.1 AA. Aplica por tratarse de dashboard gob federal.
3. Mapping PPT para los 28 indicadores del bloque principal pendientes. Patrón validado con INPC. Trabajo mecánico.
4. Umbrales calibrados para los 28 indicadores en neutro.
5. Gobernanza. Definir mantenimiento cuando autor original no esté.

## Rutas descartadas

Ingesta vía API BIE/BISE (Banco de Indicadores INEGI). Evaluada y abandonada por costo de descubrimiento de IDs (el Constructor de Consultas requiere extracción manual slide por slide de los 33 indicadores, y validación contra nombres oficiales). La PPT mensual de Presidencia ya trae todo consolidado con la misma cadencia, aprovecha trabajo institucional existente, y elimina dependencia externa. Artefactos BIE (`ingest_bie.py`, `build_mapping.py`, `bie_lotes.json`, `bie_mapping.json`) pueden archivarse.
