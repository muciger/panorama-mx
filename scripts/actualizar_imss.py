"""
actualizar_imss.py — Workflow de actualización mensual IMSS

USO:
    Desde la carpeta scripts/:
        python3 actualizar_imss.py

    O desde cualquier lugar:
        python3 /ruta/al/proyecto/scripts/actualizar_imss.py

PASOS:
    1. Descarga el CSV nuevo de datos.imss.gob.mx
    2. Colócalo en la carpeta fuente_csv/
    3. Corre este script — detecta el CSV, lo convierte a parquet
       y regenera automáticamente tableros/tablero_cruces_imss.html

REQUISITOS:
    pip install pandas duckdb openpyxl pyarrow
"""

import os, time, json, sys
import pandas as pd
import duckdb

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE        = os.path.dirname(SCRIPTS_DIR)           # raíz del proyecto
SRC_DIR     = os.path.join(BASE, "fuente_csv")       # CSVs nuevos aquí
PAR_DIR = os.path.join(BASE, "datos", "imss_parquet")
CAT_XL  = os.path.join(BASE, "datos", "catalogos.xlsx")

COLUMNAS = [
    "cve_entidad","cve_municipio","sector_economico_1","sector_economico_2",
    "sector_economico_4","tamaño_patron","sexo","rango_edad","rango_salarial",
    "asegurados","no_trabajadores","ta","teu","tec","tpu","tpc",
    "ta_sal","teu_sal","tec_sal","tpu_sal","tpc_sal",
]
DTYPES = {
    "cve_entidad": "Int16", "cve_municipio": "category",
    "sector_economico_1": "Int8", "sector_economico_2": "Int8",
    "sector_economico_4": "Int16", "tamaño_patron": "category",
    "sexo": "Int8", "rango_edad": "category", "rango_salarial": "category",
}

# ── 1. Detectar CSVs nuevos ──────────────────────────────────────────────────

def enc(path):
    return "utf-8-sig" if open(path, "rb").read(3) == b"\xef\xbb\xbf" else "latin-1"

def csv_to_parquet(csv_path):
    fname  = os.path.basename(csv_path)
    pname  = fname.replace(".csv", ".parquet")
    ppath  = os.path.join(PAR_DIR, pname)
    fecha  = fname.replace("asg-", "").replace(".csv", "")
    print(f"  Procesando {fname}...", end=" ", flush=True)
    t0 = time.time()
    df = pd.read_csv(csv_path, sep="|", encoding=enc(csv_path),
                     usecols=COLUMNAS, dtype=DTYPES)
    df["fecha"] = pd.to_datetime(fecha)
    df.to_parquet(ppath, index=False, compression="snappy")
    print(f"{len(df):,} filas — {os.path.getsize(ppath)/1e6:.1f} MB — {time.time()-t0:.0f}s")
    return ppath

print("=" * 60)
print("IMSS Empleo — Actualización mensual")
print("=" * 60)

if not os.path.exists(SRC_DIR):
    print(f"\nNo existe la carpeta fuente_csv/ en {BASE}")
    print("Descarga el CSV nuevo de datos.imss.gob.mx y ponlo ahí.")
    sys.exit(1)

csvs = sorted([
    f for f in os.listdir(SRC_DIR)
    if f.startswith("asg-") and f.endswith(".csv")
    and os.path.getsize(os.path.join(SRC_DIR, f)) > 100e6  # >100 MB = archivo real
    and not os.path.exists(os.path.join(PAR_DIR, f.replace(".csv", ".parquet")))
])

if not csvs:
    print("\nNo hay CSVs nuevos para procesar.")
    print("Si ya tienes el archivo, verifica que esté en la carpeta fuente_csv/")
else:
    print(f"\n{len(csvs)} CSV(s) nuevo(s) encontrado(s):")
    for f in csvs:
        csv_to_parquet(os.path.join(SRC_DIR, f))

# ── 2. Recalcular agregaciones 2D ────────────────────────────────────────────

print("\nRecalculando agregaciones 2D...")
PARQUET = os.path.join(PAR_DIR, "*.parquet")
con = duckdb.connect()

def agg(label, sql, outfile):
    t0 = time.time()
    df = con.execute(sql).df()
    print(f"  {label}: {len(df):,} filas — {time.time()-t0:.0f}s")
    df.to_json(outfile, orient="records")

AGGS = os.path.join(BASE, "datos", "_agg_temp")
os.makedirs(AGGS, exist_ok=True)

agg("entidad x sector", f"""
    SELECT strftime(fecha,'%Y-%m') mes, cve_entidad, sector_economico_1,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE cve_entidad IS NOT NULL AND sector_economico_1 IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_ent_sec.json")

agg("entidad x sexo", f"""
    SELECT strftime(fecha,'%Y-%m') mes, cve_entidad, sexo,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE cve_entidad IS NOT NULL AND sexo IN (1,2)
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_ent_sexo.json")

agg("entidad x tamaño", f"""
    SELECT strftime(fecha,'%Y-%m') mes, cve_entidad, tamaño_patron,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE cve_entidad IS NOT NULL AND tamaño_patron IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_ent_tam.json")

agg("sector x sexo", f"""
    SELECT strftime(fecha,'%Y-%m') mes, sector_economico_1, sexo,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE sector_economico_1 IS NOT NULL AND sexo IN (1,2)
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_sec_sexo.json")

agg("sector x tamaño", f"""
    SELECT strftime(fecha,'%Y-%m') mes, sector_economico_1, tamaño_patron,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE sector_economico_1 IS NOT NULL AND tamaño_patron IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_sec_tam.json")

agg("sector x salario", f"""
    SELECT strftime(fecha,'%Y-%m') mes, sector_economico_1, rango_salarial,
           SUM(ta) ta
    FROM read_parquet('{PARQUET}')
    WHERE sector_economico_1 IS NOT NULL AND rango_salarial IS NOT NULL
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_sec_sal.json")

agg("tamaño x sexo", f"""
    SELECT strftime(fecha,'%Y-%m') mes, tamaño_patron, sexo,
           SUM(ta) ta, SUM(tpu) tpu, SUM(teu) teu
    FROM read_parquet('{PARQUET}')
    WHERE tamaño_patron IS NOT NULL AND sexo IN (1,2)
    GROUP BY 1,2,3 ORDER BY 1,2,3
""", f"{AGGS}/agg_tam_sexo.json")

# ── 3. Regenerar tablero de cruces ───────────────────────────────────────────

print("\nRegenerando tablero_cruces_imss.html...")

sector_short = {
    "0": "Agricultura", "1": "Extractivas", "3": "Manufactura",
    "4": "Construcción", "5": "Electricidad/Agua", "6": "Comercio",
    "7": "Transportes", "8": "Servicios Empresas", "9": "Servicios Sociales",
}

xl = pd.ExcelFile(CAT_XL)

def cat_int(sheet, kc, vc):
    df = pd.read_excel(xl, sheet)[[kc, vc]].dropna(subset=[kc])
    return {str(int(r[kc])): str(r[vc]) for _, r in df.iterrows()}

def cat_str(sheet, kc, vc):
    df = pd.read_excel(xl, sheet)[[kc, vc]].dropna(subset=[kc])
    return {str(r[kc]): str(r[vc]) for _, r in df.iterrows()}

cats = {
    "entidad": cat_int("entidades",     "cve_entidad_num",  "desc_entidad"),
    "sector":  sector_short,
    "tamano":  cat_str("tamaño_patron", "tamaño_patron",    "desc_tamaño"),
    "sexo":    cat_int("sexo",          "sexo",             "desc_sexo"),
    "salario": cat_str("rango_salarial","rango_salarial",   "desc_salarial"),
}

combo_cfg = {
    "ent_sec":  ("agg_ent_sec.json",  "cve_entidad", "sector_economico_1", "entidad","sector",  ["ta","tpu","teu"]),
    "ent_sexo": ("agg_ent_sexo.json", "cve_entidad", "sexo",               "entidad","sexo",    ["ta","tpu","teu"]),
    "ent_tam":  ("agg_ent_tam.json",  "cve_entidad", "tamaño_patron",      "entidad","tamano",  ["ta","tpu","teu"]),
    "sec_sexo": ("agg_sec_sexo.json", "sector_economico_1","sexo",         "sector", "sexo",    ["ta","tpu","teu"]),
    "sec_tam":  ("agg_sec_tam.json",  "sector_economico_1","tamaño_patron","sector", "tamano",  ["ta","tpu","teu"]),
    "sec_sal":  ("agg_sec_sal.json",  "sector_economico_1","rango_salarial","sector","salario", ["ta"]),
    "tam_sexo": ("agg_tam_sexo.json", "tamaño_patron","sexo",              "tamano", "sexo",    ["ta","tpu","teu"]),
}

data = {}
for key, (fname, d1c, d2c, cat1, cat2, metrics) in combo_cfg.items():
    with open(f"{AGGS}/{fname}") as f:
        rows = json.load(f)

    def cast(r, col):
        v = r[col]
        if col in ("cve_entidad","sexo","sector_economico_1"):
            return str(int(v))
        return str(v)

    rec = {
        "mes": [r["mes"] for r in rows],
        "d1":  [cast(r, d1c) for r in rows],
        "d2":  [cast(r, d2c) for r in rows],
        "ta":  [r["ta"]  for r in rows],
        "cat1": cat1, "cat2": cat2, "metrics": metrics,
    }
    for m in ["tpu","teu"]:
        if m in metrics and rows and m in rows[0]:
            rec[m] = [r[m] for r in rows]
    data[key] = rec

payload = json.dumps({"data": data, "cats": cats}, ensure_ascii=False)

# Leer el HTML actual y reemplazar solo el payload
html_path = os.path.join(BASE, "tableros", "tablero_cruces_imss.html")
with open(html_path, encoding="utf-8") as f:
    html = f.read()

marker = "const RAW = "
start  = html.index(marker) + len(marker)
end    = html.index(";\n\nconst DATA", start)
html   = html[:start] + payload + html[end:]

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

size = os.path.getsize(html_path) / 1e6
print(f"  tablero_cruces_imss.html actualizado — {size:.2f} MB")
print("\nActualización completada.")
