"""
ingest_imss.py — Ingesta de empleo formal IMSS desde parquets mensuales.

USO:
    python3 scripts/ingest_imss.py

Genera: data/empleo_imss.json

Fuente: sources/imss/parquet/*.parquet
        Microdatos IMSS datos abiertos — datos.imss.gob.mx
        Cobertura: ene-2019 a último mes disponible.

Métricas clave:
    ta          puestos de trabajo afiliados (empleo formal total)
    tpu + tpc   puestos permanentes (urbanos + campo)
    teu + tec   puestos eventuales  (urbanos + campo)
    asegurados  total asegurados (incluye sin empleo; no usar como métrica de empleo)
"""

import json
import sys
import logging
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

# ── Rutas ────────────────────────────────────────────────────────────────────
# IMSS_PARQUET_DIR puede sobreescribirse vía env var. Si no existe la default,
# busca en rutas alternativas conocidas antes de fallar.
import os as _os

ROOT    = Path(__file__).parent.parent
CAT_XL  = ROOT / "sources" / "imss" / "catalogos.xlsx"
OUT     = ROOT / "data" / "empleo_imss.json"

_DEFAULT_PARDIRS = [
    Path(_os.environ["IMSS_PARQUET_DIR"]) if _os.environ.get("IMSS_PARQUET_DIR") else None,
    ROOT / "sources" / "imss" / "parquet",
    Path.home() / "Desktop" / "Descargas firefox" / "Datos empleo IMSS" / "Datos empleo imss" / "datos" / "imss_parquet",
    Path.home() / "Desktop" / "Descargas firefox" / "Datos empleo IMSS",
    Path.home() / "Documents" / "GitHub" / "imss-empleo" / "datos" / "imss_parquet",
]
PAR_DIR = next((p for p in _DEFAULT_PARDIRS if p and p.exists() and any(p.glob("*.parquet"))), _DEFAULT_PARDIRS[1])
PARQUET = str(PAR_DIR / "*.parquet")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Normalización de nombres para tile_map ────────────────────────────────────

# tile_map.py espera nombres cortos sin sufijos geográficos
NOMBRE_CORTO = {
    "Coahuila de Zaragoza":            "Coahuila",
    "Michoacán de Ocampo":             "Michoacán",
    "Veracruz de Ignacio de la Llave": "Veracruz",
    "Estado México":                   "México",
}

SECTOR_SHORT = {
    0: "Agricultura",
    1: "Extractivas",
    3: "Manufactura",
    4: "Construcción",
    5: "Electricidad y Agua",
    6: "Comercio",
    7: "Transportes y Comunicaciones",
    8: "Servicios para Empresas",
    9: "Servicios Sociales y Comunales",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def periodo_str(fecha) -> str:
    """datetime → 'mar-26' """
    MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
    return f"{MESES[fecha.month - 1]}-{str(fecha.year)[2:]}"


def load_entidades_cat() -> dict[int, str]:
    xl = pd.ExcelFile(CAT_XL)
    df = xl.parse("entidades")[["cve_entidad_num", "desc_entidad"]].dropna()
    result = {}
    for _, row in df.iterrows():
        nombre = str(row["desc_entidad"])
        nombre = NOMBRE_CORTO.get(nombre, nombre)
        result[int(row["cve_entidad_num"])] = nombre
    return result


def geo_str(cve: int) -> str:
    return f"{cve:02d}"


# ── Consultas DuckDB ──────────────────────────────────────────────────────────

def query_nacional_yoy(con) -> pd.DataFrame:
    """YoY mensual del total nacional (toda la historia disponible)."""
    return con.execute(f"""
        WITH monthly AS (
            SELECT fecha, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            GROUP BY fecha
        )
        SELECT
            m.fecha,
            ROUND((m.ta - p.ta) * 100.0 / NULLIF(p.ta, 0), 2) AS var_anual
        FROM monthly m
        LEFT JOIN monthly p
            ON YEAR(p.fecha) = YEAR(m.fecha) - 1
           AND MONTH(p.fecha) = MONTH(m.fecha)
        WHERE p.ta IS NOT NULL
        ORDER BY m.fecha
    """).df()


def query_sector_historico(con) -> pd.DataFrame:
    """YoY mensual por sector económico (nivel 1), toda la historia disponible."""
    return con.execute(f"""
        WITH monthly AS (
            SELECT fecha, sector_economico_1, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE sector_economico_1 IS NOT NULL
            GROUP BY fecha, sector_economico_1
        )
        SELECT
            m.fecha,
            m.sector_economico_1 AS cve_sector,
            ROUND((m.ta - p.ta) * 100.0 / NULLIF(p.ta, 0), 2) AS var_anual
        FROM monthly m
        LEFT JOIN monthly p
            ON m.sector_economico_1 = p.sector_economico_1
           AND YEAR(p.fecha)  = YEAR(m.fecha)  - 1
           AND MONTH(p.fecha) = MONTH(m.fecha)
        WHERE p.ta IS NOT NULL
        ORDER BY m.sector_economico_1, m.fecha
    """).df()


def query_nacional(con) -> pd.DataFrame:
    """Serie nacional mensual: total, permanentes, eventuales, hombres, mujeres."""
    return con.execute(f"""
        SELECT
            fecha,
            SUM(ta)            AS Total,
            SUM(tpu + tpc)     AS Permanentes,
            SUM(teu + tec)     AS Eventuales,
            SUM(CASE WHEN sexo = 1 THEN ta ELSE 0 END) AS Hombres,
            SUM(CASE WHEN sexo = 2 THEN ta ELSE 0 END) AS Mujeres
        FROM read_parquet('{PARQUET}')
        GROUP BY fecha
        ORDER BY fecha
    """).df()


def query_sector(con, fecha_actual: str) -> pd.DataFrame:
    """Desglose por sector económico (nivel 1) en el último mes disponible,
    con variación mensual y anual."""
    return con.execute(f"""
        WITH ref AS (
            SELECT sector_economico_1, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE fecha = '{fecha_actual}'
              AND sector_economico_1 IS NOT NULL
            GROUP BY 1
        ),
        mes_ant AS (
            SELECT sector_economico_1, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE fecha = (
                SELECT MAX(fecha) FROM read_parquet('{PARQUET}')
                WHERE fecha < '{fecha_actual}'
            )
              AND sector_economico_1 IS NOT NULL
            GROUP BY 1
        ),
        anio_ant AS (
            SELECT sector_economico_1, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE fecha = (
                SELECT MAX(fecha) FROM read_parquet('{PARQUET}')
                WHERE YEAR(fecha) = YEAR('{fecha_actual}'::DATE) - 1
                  AND MONTH(fecha) = MONTH('{fecha_actual}'::DATE)
            )
              AND sector_economico_1 IS NOT NULL
            GROUP BY 1
        )
        SELECT
            r.sector_economico_1                                   AS cve_sector,
            r.ta                                                   AS Total,
            ROUND((r.ta - m.ta) * 100.0 / NULLIF(m.ta, 0), 2)   AS Var_mensual,
            ROUND((r.ta - a.ta) * 100.0 / NULLIF(a.ta, 0), 2)   AS Var_anual
        FROM ref r
        LEFT JOIN mes_ant  m ON r.sector_economico_1 = m.sector_economico_1
        LEFT JOIN anio_ant a ON r.sector_economico_1 = a.sector_economico_1
        ORDER BY r.ta DESC
    """).df()


def query_genero_por_sector(con, fecha_actual: str) -> pd.DataFrame:
    """Brecha de género por sector en el último mes disponible.
    Devuelve hombres, mujeres y % mujeres por cve_sector."""
    return con.execute(f"""
        SELECT
            sector_economico_1 AS cve_sector,
            SUM(CASE WHEN sexo = 1 THEN ta ELSE 0 END) AS hombres,
            SUM(CASE WHEN sexo = 2 THEN ta ELSE 0 END) AS mujeres,
            SUM(ta) AS total,
            ROUND(SUM(CASE WHEN sexo = 2 THEN ta ELSE 0 END) * 100.0 / NULLIF(SUM(ta), 0), 1) AS pct_mujeres
        FROM read_parquet('{PARQUET}')
        WHERE fecha = '{fecha_actual}'
          AND sector_economico_1 IS NOT NULL
          AND sexo IN (1, 2)
        GROUP BY 1
        ORDER BY total DESC
    """).df()


def query_top_subsectores_yoy(con, fecha_actual: str, top_n: int = 10, min_total: int = 50000) -> pd.DataFrame:
    """Top N subsectores (sec1, sec2) con mayor variación anual.
    min_total filtra sectores con menos de N puestos para evitar ruido."""
    return con.execute(f"""
        WITH s AS (
            SELECT strftime(fecha, '%Y-%m') AS mes,
                   sector_economico_1 AS sec1,
                   sector_economico_2 AS sec2,
                   SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE sector_economico_2 IS NOT NULL
              AND sector_economico_1 IS NOT NULL
            GROUP BY 1, 2, 3
        )
        SELECT
            a.sec1, a.sec2,
            a.ta AS ta_actual,
            b.ta AS ta_anio_ant,
            ROUND(100.0 * (a.ta::DOUBLE / NULLIF(b.ta, 0) - 1), 2) AS var_anual
        FROM s a
        JOIN s b ON a.sec1 = b.sec1 AND a.sec2 = b.sec2
        WHERE a.mes = strftime('{fecha_actual}'::DATE, '%Y-%m')
          AND b.mes = strftime(('{fecha_actual}'::DATE - INTERVAL 1 YEAR), '%Y-%m')
          AND a.ta > {min_total}
        ORDER BY var_anual DESC
        LIMIT {top_n * 2}
    """).df()


def query_hito_outsourcing(con) -> pd.DataFrame:
    """Serie del sec2=88 (servicios empresariales/outsourcing) para marcar hito de abril 2021."""
    return con.execute(f"""
        SELECT
            strftime(fecha, '%Y-%m') AS mes,
            SUM(ta) AS ta_outsourcing
        FROM read_parquet('{PARQUET}')
        WHERE sector_economico_2 = 88
        GROUP BY 1
        ORDER BY 1
    """).df()


def query_entidad(con, fecha_actual: str) -> pd.DataFrame:
    """Desglose por entidad federativa en el último mes disponible,
    con variación anual y participación en el total."""
    return con.execute(f"""
        WITH ref AS (
            SELECT cve_entidad, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE fecha = '{fecha_actual}'
              AND cve_entidad IS NOT NULL
            GROUP BY 1
        ),
        anio_ant AS (
            SELECT cve_entidad, SUM(ta) AS ta
            FROM read_parquet('{PARQUET}')
            WHERE fecha = (
                SELECT MAX(fecha) FROM read_parquet('{PARQUET}')
                WHERE YEAR(fecha) = YEAR('{fecha_actual}'::DATE) - 1
                  AND MONTH(fecha) = MONTH('{fecha_actual}'::DATE)
            )
              AND cve_entidad IS NOT NULL
            GROUP BY 1
        ),
        total AS (
            SELECT SUM(ta) AS total_nacional
            FROM read_parquet('{PARQUET}')
            WHERE fecha = '{fecha_actual}'
        )
        SELECT
            r.cve_entidad,
            r.ta                                                        AS Total,
            ROUND((r.ta - a.ta) * 100.0 / NULLIF(a.ta, 0), 2)        AS Var_anual,
            ROUND(r.ta * 100.0 / NULLIF(t.total_nacional, 0), 2)      AS Participacion
        FROM ref r
        LEFT JOIN anio_ant a ON r.cve_entidad = a.cve_entidad
        CROSS JOIN total t
        ORDER BY r.ta DESC
    """).df()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not PAR_DIR.exists():
        log.error("No existe %s", PAR_DIR)
        sys.exit(1)

    parquets = sorted(PAR_DIR.glob("*.parquet"))
    if not parquets:
        log.error("No hay parquets en %s", PAR_DIR)
        sys.exit(1)

    log.info("Conectando DuckDB — %d parquets (%s → %s)",
             len(parquets), parquets[0].stem, parquets[-1].stem)

    con = duckdb.connect()
    ent_cat = load_entidades_cat()

    # ── 1. Serie nacional ────────────────────────────────────────────────────
    log.info("Aggregando serie nacional...")
    df_nac = query_nacional(con)

    fecha_actual_dt = df_nac["fecha"].max()
    fecha_actual    = fecha_actual_dt.strftime("%Y-%m-%d")
    periodo_ref     = periodo_str(fecha_actual_dt)

    series = []
    for _, row in df_nac.iterrows():
        series.append({
            "Periodo":     periodo_str(row["fecha"]),
            "Total":       int(row["Total"]),
            "Permanentes": int(row["Permanentes"]),
            "Eventuales":  int(row["Eventuales"]),
            "Hombres":     int(row["Hombres"]),
            "Mujeres":     int(row["Mujeres"]),
        })
    log.info("  %d periodos — último: %s — Total: %s puestos",
             len(series), periodo_ref, f"{series[-1]['Total']:,}")

    # ── 2. Sector ────────────────────────────────────────────────────────────
    log.info("Aggregando por sector (%s)...", periodo_ref)
    df_sec = query_sector(con, fecha_actual)

    series_sector = []
    for _, row in df_sec.iterrows():
        cve = int(row["cve_sector"]) if pd.notna(row["cve_sector"]) else None
        if cve is None:
            continue
        series_sector.append({
            "Sector":      SECTOR_SHORT.get(cve, f"Sector {cve}"),
            "cve_sector":  cve,
            "Total":       int(row["Total"]),
            "Var_mensual": float(row["Var_mensual"]) if pd.notna(row["Var_mensual"]) else None,
            "Var_anual":   float(row["Var_anual"])   if pd.notna(row["Var_anual"])   else None,
        })
    log.info("  %d sectores", len(series_sector))

    # ── 3. YoY histórico nacional ────────────────────────────────────────────
    log.info("Aggregando YoY nacional histórico...")
    df_yoy = query_nacional_yoy(con)
    series_nacional_yoy = {
        "periodos":  [periodo_str(r["fecha"]) for _, r in df_yoy.iterrows()],
        "var_anual": [float(r["var_anual"]) if pd.notna(r["var_anual"]) else None
                      for _, r in df_yoy.iterrows()],
    }
    log.info("  %d periodos YoY — último: %.2f%%", len(series_nacional_yoy["periodos"]),
             series_nacional_yoy["var_anual"][-1] if series_nacional_yoy["var_anual"] else 0)

    # ── 4. YoY histórico por sector ──────────────────────────────────────────
    log.info("Aggregando YoY por sector (histórico)...")
    df_sec_hist = query_sector_historico(con)

    series_sector_yoy: dict[str, dict] = {}
    for cve_s in df_sec_hist["cve_sector"].unique():
        cve = int(cve_s) if pd.notna(cve_s) else None
        if cve is None:
            continue
        nombre = SECTOR_SHORT.get(cve, f"Sector {cve}")
        sub = df_sec_hist[df_sec_hist["cve_sector"] == cve_s].sort_values("fecha")
        series_sector_yoy[nombre] = {
            "periodos":  [periodo_str(r["fecha"]) for _, r in sub.iterrows()],
            "var_anual": [float(r["var_anual"]) if pd.notna(r["var_anual"]) else None
                          for _, r in sub.iterrows()],
            "cve_sector": cve,
        }
    log.info("  %d sectores con serie histórica", len(series_sector_yoy))

    # ── 5. Entidad ───────────────────────────────────────────────────────────
    log.info("Aggregando por entidad (%s)...", periodo_ref)
    df_ent = query_entidad(con, fecha_actual)

    series_entidad = []
    for _, row in df_ent.iterrows():
        cve = int(row["cve_entidad"]) if pd.notna(row["cve_entidad"]) else None
        if cve is None or cve not in ent_cat:
            continue
        series_entidad.append({
            "Entidad":      ent_cat[cve],
            "_geo":         geo_str(cve),
            "Total":        int(row["Total"]),
            "Var_anual":    float(row["Var_anual"])    if pd.notna(row["Var_anual"])    else None,
            "Participacion":float(row["Participacion"])if pd.notna(row["Participacion"])else None,
            "_periodo":     periodo_ref,
        })
    log.info("  %d entidades", len(series_entidad))

    # ── 6. Brecha de género por sector ──────────────────────────────────────
    log.info("Aggregando género por sector (%s)...", periodo_ref)
    df_gen = query_genero_por_sector(con, fecha_actual)
    genero_por_sector = []
    for _, row in df_gen.iterrows():
        cve = int(row["cve_sector"]) if pd.notna(row["cve_sector"]) else None
        if cve is None:
            continue
        genero_por_sector.append({
            "cve_sector": cve,
            "sector":     SECTOR_SHORT.get(cve, f"Sector {cve}"),
            "hombres":    int(row["hombres"]),
            "mujeres":    int(row["mujeres"]),
            "total":      int(row["total"]),
            "pct_mujeres": float(row["pct_mujeres"]) if pd.notna(row["pct_mujeres"]) else None,
        })
    log.info("  %d sectores con datos de género", len(genero_por_sector))

    # ── 7. Top subsectores con mayor crecimiento anual ──────────────────────
    log.info("Aggregando top subsectores YoY (%s)...", periodo_ref)
    try:
        df_top = query_top_subsectores_yoy(con, fecha_actual)
        top_subsectores_yoy = []
        for _, row in df_top.iterrows():
            sec1 = int(row["sec1"]) if pd.notna(row["sec1"]) else None
            sec2 = int(row["sec2"]) if pd.notna(row["sec2"]) else None
            if sec1 is None or sec2 is None:
                continue
            top_subsectores_yoy.append({
                "sec1": sec1,
                "sec2": sec2,
                "sector": SECTOR_SHORT.get(sec1, f"Sector {sec1}"),
                "subsector_id": f"{sec1}-{sec2}",
                "ta_actual":    int(row["ta_actual"]),
                "ta_anio_ant":  int(row["ta_anio_ant"]),
                "var_anual":    float(row["var_anual"]) if pd.notna(row["var_anual"]) else None,
            })
        # Top alza y top baja
        top_subsectores_yoy.sort(key=lambda x: -(x["var_anual"] or 0))
        top_alza = top_subsectores_yoy[:10]
        top_baja = sorted(top_subsectores_yoy, key=lambda x: (x["var_anual"] or 0))[:10]
        log.info("  %d subsectores con variación anual", len(top_subsectores_yoy))
    except Exception as exc:
        log.warning("Top subsectores YoY falló: %s", exc)
        top_alza = []
        top_baja = []

    # ── 8. Hito outsourcing (sec2=88) ───────────────────────────────────────
    log.info("Aggregando serie sec2=88 para hito outsourcing...")
    try:
        df_outs = query_hito_outsourcing(con)
        outsourcing = [
            {"periodo": r["mes"], "ta": int(r["ta_outsourcing"])}
            for _, r in df_outs.iterrows()
            if pd.notna(r["ta_outsourcing"])
        ]
        log.info("  %d periodos de outsourcing (sec2=88)", len(outsourcing))
    except Exception as exc:
        log.warning("Serie outsourcing falló: %s", exc)
        outsourcing = []

    # ── 9. Ensamblar JSON ────────────────────────────────────────────────────
    ultimo_total = series[-1]["Total"]
    total_ant    = series[-2]["Total"] if len(series) >= 2 else None
    delta_m      = round((ultimo_total - total_ant) / total_ant * 100, 2) if total_ant else None

    anio_ant_idx = next((i for i, s in enumerate(reversed(series))
                         if s["Periodo"][4:] != periodo_ref[4:]), None)
    total_aa     = series[-(anio_ant_idx + 1)]["Total"] if anio_ant_idx else None
    delta_a      = round((ultimo_total - total_aa) / total_aa * 100, 2) if total_aa else None

    doc = {
        "id":          "empleo_imss",
        "nombre":      "Empleo formal IMSS",
        "categoria":   "empleo",
        "frecuencia":  "mensual",
        "unidad":      "puestos de trabajo afiliados",
        "fuente_url":  "https://datos.imss.gob.mx",
        "sheet_origen": "parquet",
        "titulo_original":    "Trabajadores asegurados en el IMSS",
        "subtitulo_original": "Puestos de trabajo afiliados (ta), último día del mes",
        "columnas":           ["Periodo","Total","Permanentes","Eventuales","Hombres","Mujeres"],
        "columnas_normalizadas": ["Periodo","Total","Permanentes","Eventuales","Hombres","Mujeres"],
        "ultima_actualizacion":  datetime.today().strftime("%Y-%m-%d"),
        "proxima_actualizacion_manual": None,
        "periodos":    [s["Periodo"] for s in series],
        "series":      series,
        "series_sector":      series_sector,
        "series_nacional_yoy": series_nacional_yoy,
        "series_sector_yoy":  series_sector_yoy,
        "series_entidad":     series_entidad,
        "genero_por_sector":  genero_por_sector,
        "top_subsectores_alza": top_alza,
        "top_subsectores_baja": top_baja,
        "serie_outsourcing_sec88": outsourcing,
        "periodo_referencia": periodo_ref,
        "_ultimo_total":   ultimo_total,
        "_delta_mensual":  delta_m,
        "_delta_anual":    delta_a,
        "_permanentes_pct": round(series[-1]["Permanentes"] / ultimo_total * 100, 1),
        "_eventuales_pct":  round(series[-1]["Eventuales"]  / ultimo_total * 100, 1),
        "_mujeres_pct":     round(series[-1]["Mujeres"]     / ultimo_total * 100, 1),
        "benchmarks":      {},
        "alertas_activas": [],
        "fuente_ingest":   "parquet_imss",
    }

    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    log.info("Escrito %s (%.0f KB) — %s puestos — Δm=%s%% Δa=%s%%",
             OUT.name, size_kb, f"{ultimo_total:,}",
             delta_m if delta_m is not None else "N/A",
             delta_a if delta_a is not None else "N/A")


if __name__ == "__main__":
    main()
