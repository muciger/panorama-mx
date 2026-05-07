#!/usr/bin/env python3
"""
Seed one-shot de 4 indicadores nuevos desde el XLSX embebido del Reporte mensual
INEGI abril 2026. Produce data/enoe_mensual.json, pib_estatal.json,
itaee_estatal.json, imai_estatal.json con el schema estándar del dashboard.

Uso:
    python3 scripts/seed_new_indicators.py [--dry-run]

ENOE mensual usa schema temporal (periodos = ['mmm-yy'...], series = list[dict]).
Los 3 estatal usan schema cross-sectional (periodos = [entidades], series =
list[dict] ordenados). Idempotente: si el JSON ya existe conserva metadata
(alertas_activas, _productos, _entidades_ciudades) y sobreescribe el resto.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SOURCES_DIR = ROOT / "sources"
XLSX_DEFAULT = SOURCES_DIR / "Datos_embebidos_Reporte_indicadores_abril_2026.xlsx"

MESES_ABREV = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def date_to_periodo(d: dt.datetime) -> str:
    return f"{MESES_ABREV[d.month - 1]}-{str(d.year)[-2:]}"


def periodo_sort_key(p: str):
    try:
        mes, yy = p.split("-")
        return (2000 + int(yy), MESES_ABREV.index(mes.lower()))
    except Exception:
        return (9999, 99)


def to_num(v, decimals: int = 4):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        fv = float(v)
        return round(fv, decimals)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "ND", "nd", "N.D."):
        return None
    try:
        return round(float(s), decimals)
    except ValueError:
        return None


def compute_ma12(arr):
    """Ventana móvil 12, mínimo 3 valores no nulos. Igual que normalize.py."""
    out = [None] * len(arr)
    for i in range(len(arr)):
        lo = max(0, i - 11)
        window = [x for x in arr[lo : i + 1] if x is not None]
        if len(window) >= 3:
            out[i] = round(sum(window) / len(window), 4)
    return out


def load_existing(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def preserve_meta(existing: dict) -> dict:
    """Campos que la ingesta NO debe sobreescribir si ya existen en disco."""
    keep = {}
    for k in ("alertas_activas", "_productos", "_entidades_ciudades"):
        if k in existing:
            keep[k] = existing[k]
    return keep


def read_sheet(wb, name):
    ws = wb[name]
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(list(r))
    return rows


# ---------- ENOE mensual ----------


def build_enoe_mensual(wb, existing: dict) -> dict:
    # g1: participación Total/Hombres/Mujeres
    # g2: subocupación Total
    # g3: desocupación Total/Hombres/Mujeres
    # g4: informalidad laboral
    g1 = read_sheet(wb, "25_ENOE_empleo_g1")
    g2 = read_sheet(wb, "25_ENOE_empleo_g2")
    g3 = read_sheet(wb, "25_ENOE_empleo_g3")
    g4 = read_sheet(wb, "25_ENOE_empleo_g4")

    def parse_temporal(rows, header_row=2):
        out = {}
        for row in rows[header_row + 1 :]:
            d = row[0]
            if not isinstance(d, dt.datetime):
                continue
            out[date_to_periodo(d)] = row
        return out

    m1 = parse_temporal(g1)
    m2 = parse_temporal(g2)
    m3 = parse_temporal(g3)
    m4 = parse_temporal(g4)

    all_periods = sorted(set(m1) | set(m2) | set(m3) | set(m4), key=periodo_sort_key)

    cols = [
        "Periodo",
        "Tasa_participacion_Total",
        "Tasa_participacion_Hombres",
        "Tasa_participacion_Mujeres",
        "Tasa_subocupacion",
        "Tasa_desocupacion_Total",
        "Tasa_desocupacion_Hombres",
        "Tasa_desocupacion_Mujeres",
        "Tasa_informalidad",
    ]

    series = []
    for p in all_periods:
        r1 = m1.get(p, [None] * 4)
        r2 = m2.get(p, [None] * 4)
        r3 = m3.get(p, [None] * 4)
        r4 = m4.get(p, [None] * 4)
        series.append(
            {
                "Periodo": p,
                "Tasa_participacion_Total": to_num(r1[1] if len(r1) > 1 else None, 2),
                "Tasa_participacion_Hombres": to_num(r1[2] if len(r1) > 2 else None, 2),
                "Tasa_participacion_Mujeres": to_num(r1[3] if len(r1) > 3 else None, 2),
                "Tasa_subocupacion": to_num(r2[1] if len(r2) > 1 else None, 2),
                "Tasa_desocupacion_Total": to_num(r3[1] if len(r3) > 1 else None, 2),
                "Tasa_desocupacion_Hombres": to_num(r3[2] if len(r3) > 2 else None, 2),
                "Tasa_desocupacion_Mujeres": to_num(r3[3] if len(r3) > 3 else None, 2),
                "Tasa_informalidad": to_num(r4[1] if len(r4) > 1 else None, 2),
            }
        )

    benchmarks = {
        "ma12_Tasa_desocupacion_Total": compute_ma12([row["Tasa_desocupacion_Total"] for row in series])
    }

    base = {
        "id": "enoe_mensual",
        "nombre": "ENOE, tasas mensuales de participación, subocupación, desocupación e informalidad",
        "categoria": "empleo",
        "frecuencia": "mensual",
        "unidad": "% de la PEA y tasas derivadas",
        "fuente_url": "https://www.inegi.org.mx/app/saladeprensa/noticia/10630",
        "sheet_origen": "ENOE_mensual",
        "titulo_original": "Encuesta Nacional de Ocupación y Empleo (mensual)",
        "subtitulo_original": "Participación, subocupación, desocupación e informalidad (%)",
        "columnas": cols,
        "columnas_normalizadas": cols,
        "ultima_actualizacion": "2026-04-10",
        "proxima_actualizacion_manual": "",
        "periodos": all_periods,
        "series": series,
        "benchmarks": benchmarks,
        "alertas_activas": [],
    }
    base.update(preserve_meta(existing))
    return base


# ---------- Cross-sectional estatales ----------


def build_cross_sectional_single(wb, sheet, col_name, decimals=2):
    """Lee una hoja XLSX cross-sectional (primera col entidad, 2da col valor)."""
    rows = read_sheet(wb, sheet)
    out = {}
    # Header en r3; datos desde r4
    for row in rows[3:]:
        ent = row[0]
        val = row[1] if len(row) > 1 else None
        if not ent or not isinstance(ent, str):
            continue
        out[ent.strip()] = to_num(val, decimals)
    return out


def build_pib_estatal(wb, existing: dict) -> dict:
    m_anual = build_cross_sectional_single(wb, "28_PIB_estatal", "Var_anual")
    entidades = sorted(m_anual.keys(), key=lambda e: (-(m_anual[e] if m_anual[e] is not None else -9999), e))
    series = [{"Entidad": e, "Var_anual": m_anual[e]} for e in entidades]
    cols = ["Entidad", "Var_anual"]

    base = {
        "id": "pib_estatal",
        "nombre": "PIB estatal, variación anual real",
        "categoria": "regional",
        "frecuencia": "anual",
        "unidad": "variación % real por entidad",
        "fuente_url": "https://www.inegi.org.mx/app/saladeprensa/noticia/10703",
        "sheet_origen": "28_PIB_estatal",
        "titulo_original": "PIB estatal",
        "subtitulo_original": "Variación anual real (%)",
        "columnas": cols,
        "columnas_normalizadas": cols,
        "ultima_actualizacion": "2026-04-10",
        "proxima_actualizacion_manual": "",
        "periodos": entidades,
        "series": series,
        "benchmarks": {},
        "alertas_activas": [],
    }
    base.update(preserve_meta(existing))
    return base


def build_itaee_estatal(wb, existing: dict) -> dict:
    m_an = build_cross_sectional_single(wb, "29_ITAEE_estatal_g1", "Var_anual")
    m_tr = build_cross_sectional_single(wb, "29_ITAEE_estatal_g2", "Var_trimestral")
    entidades = sorted(set(m_an) | set(m_tr), key=lambda e: (-(m_an.get(e) if m_an.get(e) is not None else -9999), e))
    series = [{"Entidad": e, "Var_anual": m_an.get(e), "Var_trimestral": m_tr.get(e)} for e in entidades]
    cols = ["Entidad", "Var_anual", "Var_trimestral"]
    base = {
        "id": "itaee_estatal",
        "nombre": "ITAEE, actividad económica por entidad (trimestral)",
        "categoria": "regional",
        "frecuencia": "trimestral",
        "unidad": "variación % anual y trimestral por entidad",
        "fuente_url": "https://www.inegi.org.mx/app/saladeprensa/noticia/10704",
        "sheet_origen": "29_ITAEE_estatal",
        "titulo_original": "ITAEE por entidad",
        "subtitulo_original": "Variación anual y trimestral real (%)",
        "columnas": cols,
        "columnas_normalizadas": cols,
        "ultima_actualizacion": "2026-04-10",
        "proxima_actualizacion_manual": "",
        "periodos": entidades,
        "series": series,
        "benchmarks": {},
        "alertas_activas": [],
    }
    base.update(preserve_meta(existing))
    return base


def build_imai_estatal(wb, existing: dict) -> dict:
    m_an = build_cross_sectional_single(wb, "31_IMAI_estatal_g1", "Var_anual")
    m_me = build_cross_sectional_single(wb, "31_IMAI_estatal_g2", "Var_mensual")
    entidades = sorted(set(m_an) | set(m_me), key=lambda e: (-(m_an.get(e) if m_an.get(e) is not None else -9999), e))
    series = [{"Entidad": e, "Var_anual": m_an.get(e), "Var_mensual": m_me.get(e)} for e in entidades]
    cols = ["Entidad", "Var_anual", "Var_mensual"]
    base = {
        "id": "imai_estatal",
        "nombre": "IMAI estatal, actividad industrial por entidad",
        "categoria": "regional",
        "frecuencia": "mensual",
        "unidad": "variación % anual y mensual por entidad",
        "fuente_url": "https://www.inegi.org.mx/app/saladeprensa/noticia/10705",
        "sheet_origen": "31_IMAI_estatal",
        "titulo_original": "IMAI estatal",
        "subtitulo_original": "Variación anual y mensual real (%)",
        "columnas": cols,
        "columnas_normalizadas": cols,
        "ultima_actualizacion": "2026-04-10",
        "proxima_actualizacion_manual": "",
        "periodos": entidades,
        "series": series,
        "benchmarks": {},
        "alertas_activas": [],
    }
    base.update(preserve_meta(existing))
    return base


BUILDERS = {
    "enoe_mensual": build_enoe_mensual,
    "pib_estatal": build_pib_estatal,
    "itaee_estatal": build_itaee_estatal,
    "imai_estatal": build_imai_estatal,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", type=Path, default=XLSX_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.xlsx.exists():
        print(f"ERROR: xlsx no existe: {args.xlsx}", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(args.xlsx, data_only=True)

    resultado = {}
    for ind_id, builder in BUILDERS.items():
        path = DATA_DIR / f"{ind_id}.json"
        existing = load_existing(path)
        doc = builder(wb, existing)
        resultado[ind_id] = {
            "periodos": len(doc["periodos"]),
            "primer": doc["periodos"][0] if doc["periodos"] else None,
            "ultimo": doc["periodos"][-1] if doc["periodos"] else None,
            "cols": doc["columnas_normalizadas"],
        }
        if not args.dry_run:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)

    print(json.dumps({"dry_run": args.dry_run, "indicadores": resultado}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
