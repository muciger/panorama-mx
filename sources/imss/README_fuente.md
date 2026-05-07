# Empleo formal en México — Base de datos IMSS 2019–2026

Panel de microdatos de empleo formal construido sobre los datos abiertos del IMSS. Cubre enero 2019 a marzo 2026 (87 meses). Permite analizar puestos de trabajo por estado, sector económico, tamaño de patrón, sexo, rango de edad y rango salarial.

Fuente: [datos.imss.gob.mx](https://datos.imss.gob.mx)

---

## Qué hay en esta carpeta

```
Datos empleo imss/
├── tableros/               Dashboards interactivos — ábrelos en cualquier navegador
│   ├── tablero_imss.html              Exploración por una dimensión (serie de tiempo, ranking)
│   ├── tablero_variacion_imss.html    Variaciones porcentuales: interanual, mensual, YTD
│   └── tablero_cruces_imss.html       Cruces entre dos dimensiones (ej. estado × sector)
│
├── datos/                  Datos procesados — fuente de todo análisis
│   ├── imss_parquet/                  87 archivos .parquet, uno por mes (ene 2019–mar 2026)
│   ├── catalogos.xlsx                 Catálogos de todas las dimensiones
│   └── diccionario_de_datos_1.xlsx    Diccionario original del IMSS
│
├── scripts/                Código para consultar y actualizar los datos
│   ├── actualizar_imss.py             Actualización mensual (ver instrucciones abajo)
│   ├── descargar_imss.py              Utilidad de descarga
│   └── IMSS_empleo_guia.md            Guía técnica con queries DuckDB listos para usar
│
├── documentacion/          Documentos de referencia
│   ├── Guia_usuario_datos_abiertos_asegurados.pdf
│   ├── glosario_datos_abiertos_asegurados_.pdf
│   ├── Reporte_Empleo_IMSS_2019_2026.pdf
│   └── variacion_interanual_*.png
│
└── fuente_csv/             CSVs originales del IMSS (archivos grandes, ~380 MB c/u)
```

---

## Cómo usar los tableros

Abre cualquier archivo `.html` de la carpeta `tableros/` directamente en Chrome, Firefox o Safari. No requieren conexión a internet ni instalación.

**tablero_imss.html** — Punto de entrada. Selecciona una dimensión (nacional, estado, sector, etc.), una métrica (puestos totales, permanentes, eventuales) y el rango de fechas. Muestra serie de tiempo, ranking y tabla.

**tablero_variacion_imss.html** — Enfocado en cambios porcentuales. KPIs de variación interanual y mensual, gráfica de doble eje y ranking con semáforo de color.

**tablero_cruces_imss.html** — El más flexible. Permite cruzar dos dimensiones simultáneamente. Por ejemplo: empleo en manufactura desglosado por tamaño de patrón en cada estado, o la brecha de género por sector económico a lo largo del tiempo.

Combinaciones disponibles en el tablero de cruces:

| Dim 1 | Dim 2 |
|---|---|
| Entidad federativa | Sector económico |
| Entidad federativa | Sexo |
| Entidad federativa | Tamaño de patrón |
| Sector económico | Sexo |
| Sector económico | Tamaño de patrón |
| Sector económico | Rango salarial |
| Tamaño de patrón | Sexo |

---

## Cómo consultar los datos con Python

Los archivos `.parquet` en `datos/imss_parquet/` son el formato de trabajo. Se consultan con DuckDB, que no requiere instalar una base de datos.

```python
pip install duckdb pandas openpyxl pyarrow
```

```python
import duckdb, pandas as pd

PARQUET = "datos/imss_parquet/*.parquet"
con = duckdb.connect()

# Serie nacional mensual de empleo formal
df = con.execute(f"""
    SELECT strftime(fecha, '%Y-%m') AS mes, SUM(ta) AS ta
    FROM read_parquet('{PARQUET}')
    GROUP BY 1 ORDER BY 1
""").df()
```

La guía completa con más queries está en `scripts/IMSS_empleo_guia.md`.

**Métrica clave:** usa `ta` (puestos de trabajo afiliados) para medir empleo formal. `asegurados` incluye modalidades sin empleo asociado (seguro familiar, facultativo) y sobreestima el empleo.

---

## Actualización mensual

El IMSS publica un CSV nuevo aproximadamente 10 días después del cierre de cada mes.

1. Descarga el archivo `asg-YYYY-MM-DD.csv` de [datos.imss.gob.mx](https://datos.imss.gob.mx)
2. Colócalo en la carpeta `fuente_csv/`
3. Ejecuta desde terminal:

```bash
python3 scripts/actualizar_imss.py
```

El script detecta el CSV nuevo, lo convierte a parquet (~25 MB vs ~380 MB del CSV) y regenera `tableros/tablero_cruces_imss.html` con los datos actualizados. Tarda aproximadamente 3–4 minutos.

---

## Dimensiones disponibles

| Dimensión | Descripción | Valores |
|---|---|---|
| `cve_entidad` | Entidad federativa | 1–32 |
| `cve_municipio` | Municipio | Clave alfanumérica IMSS |
| `sector_economico_1` | División económica | 9 divisiones |
| `sector_economico_2` | Grupo económico | 62 grupos |
| `sector_economico_4` | Fracción económica | 276 fracciones |
| `tamaño_patron` | Tamaño del patrón | S1 (1 puesto) a S7 (>5,000) |
| `sexo` | Sexo | 1=Hombre, 2=Mujer, 3=No binario |
| `rango_edad` | Rango de edad | E1–E14 |
| `rango_salarial` | Rango salarial | W1–W25 |

Los catálogos con las descripciones completas están en `datos/catalogos.xlsx`.

---

*Procesado con DuckDB 1.5 y pandas. Actualizado abril 2026.*
