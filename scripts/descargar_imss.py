"""
Descarga y procesa archivos mensuales de asegurados IMSS (2019-2026).
Por cada mes: descarga el CSV, selecciona columnas, agrega columna 'fecha',
guarda como parquet comprimido. Resultado: ~4-6 GB vs ~33 GB en CSV crudo.

Uso:
    pip install pandas pyarrow requests --break-system-packages
    python descargar_imss.py

Los archivos parquet quedan en la carpeta ./imss_parquet/
"""

import os
import io
import requests
import pandas as pd
from datetime import date

# ── Configuración ──────────────────────────────────────────────────────────────

OUTPUT_DIR = "imss_parquet"
BASE_URL = "http://datos.imss.gob.mx/sites/default/files"

COLUMNAS = [
    "cve_entidad", "cve_municipio",
    "sector_economico_1", "sector_economico_2", "sector_economico_4",
    "tamaño_patron", "sexo", "rango_edad", "rango_salarial",
    "asegurados", "no_trabajadores",
    "ta", "teu", "tec", "tpu", "tpc",
    "ta_sal", "teu_sal", "tec_sal", "tpu_sal", "tpc_sal",
]

# Último día de cada mes por año
def ultimo_dia(año, mes):
    if mes == 12:
        return date(año, 12, 31)
    return date(año, mes + 1, 1).replace(day=1) - __import__('datetime').timedelta(days=1)

# Generar lista de archivos 2019-2026
archivos = []
for año in range(2019, 2027):
    for mes in range(1, 13):
        d = ultimo_dia(año, mes)
        if d > date.today():
            break
        nombre = f"asg-{d.strftime('%Y-%m-%d')}"
        archivos.append((d, nombre))

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Descarga y procesamiento ───────────────────────────────────────────────────

print(f"Total de archivos a descargar: {len(archivos)}\n")

for i, (fecha, nombre) in enumerate(archivos, 1):
    parquet_path = os.path.join(OUTPUT_DIR, f"{nombre}.parquet")

    if os.path.exists(parquet_path):
        print(f"[{i:02d}/{len(archivos)}] {nombre} — ya existe, omitiendo.")
        continue

    url = f"{BASE_URL}/{nombre}.csv"
    print(f"[{i:02d}/{len(archivos)}] Descargando {nombre} ...", end=" ", flush=True)

    try:
        resp = requests.get(url, timeout=120, stream=True)
        resp.raise_for_status()

        # Leer CSV en chunks para no saturar RAM
        chunks = []
        for chunk in pd.read_csv(
            io.BytesIO(resp.content),
            usecols=COLUMNAS,
            dtype={
                "cve_entidad": "Int16",
                "cve_municipio": "category",
                "sector_economico_1": "Int8",
                "sector_economico_2": "Int8",
                "sector_economico_4": "Int16",
                "tamaño_patron": "category",
                "sexo": "Int8",
                "rango_edad": "category",
                "rango_salarial": "category",
            },
            chunksize=500_000,
        ):
            chunk["fecha"] = fecha
            chunks.append(chunk)

        df = pd.concat(chunks, ignore_index=True)
        df["fecha"] = pd.to_datetime(df["fecha"])

        df.to_parquet(parquet_path, index=False, compression="snappy")

        size_mb = os.path.getsize(parquet_path) / 1e6
        print(f"OK — {len(df):,} filas — {size_mb:.1f} MB")

    except Exception as e:
        print(f"ERROR: {e}")

print("\nListo. Archivos en ./imss_parquet/")
