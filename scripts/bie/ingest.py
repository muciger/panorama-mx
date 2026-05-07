"""Ingest desde API BIE-INEGI. Reemplaza el flujo manual desde PPT/PDF.

Lee config/bie_mapping.json, descarga series de la API por indicador, pivotea
al formato row-oriented que consume normalize.py, y reescribe data/{id}.json
preservando metadatos editoriales (nombre, categoria, fuente_url, etc.).

Uso:
    python3 scripts/bie/ingest.py                  # todos los indicadores mapeados
    python3 scripts/bie/ingest.py --id igae        # solo IGAE
    python3 scripts/bie/ingest.py --dry-run        # no escribe, solo reporta
    python3 scripts/bie/ingest.py --diff           # muestra diff vs data/{id}.json actual

Token: lee INEGI_BIE_TOKEN de env. Si no existe, intenta cargar .env del root.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
from bie.client import INEGIBIEClient  # noqa: E402

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def load_env(root: Path) -> None:
    """Carga .env si existe y la var no esta seteada."""
    if "INEGI_BIE_TOKEN" in os.environ:
        return
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def to_periodo_local(time_period: str, fmt: str, max_m_in_series: int = 12) -> str | None:
    """Convierte TIME_PERIOD BIE al formato local del indicador.

    BIE devuelve:
        - mensual:    'YYYY/MM'   ej '2026/02'
        - trimestral: 'YYYY/MM' con MM=3,6,9,12 (cierre de trimestre)
                      O 'YYYY/QQ' con QQ=1-4 (trimestre directo, según ID)
                      Detección automática vía max_m_in_series.
        - anual:      'YYYY'
        - quincenal:  'YYYY/MM/Q' ej '2026/04/1'
    """
    try:
        if fmt == "mmm-yy":
            y, m = time_period.split("/")
            return f"{MESES[int(m) - 1]}-{y[-2:]}"
        if fmt == "T-YY":
            y, m = time_period.split("/")
            m_num = int(m)
            # Si todos los m de la serie son <=4, asumimos QQ directo. Si llegan a 12, asumimos cierre mes.
            if max_m_in_series <= 4:
                tri = m_num
            else:
                tri = (m_num - 1) // 3 + 1
            return f"T{tri}-{y[-2:]}"
        if fmt == "YYYY":
            return time_period
        if fmt == "QNN-yy":
            parts = time_period.split("/")
            if len(parts) == 3:
                y, m, q = parts
                qnum = (int(m) - 1) * 2 + int(q)
                return f"Q{qnum:02d}-{y[-2:]}"
    except Exception:
        return None
    return None


ENTIDADES_GEO = [
    ("01", "Aguascalientes"), ("02", "Baja California"), ("03", "Baja California Sur"),
    ("04", "Campeche"), ("05", "Coahuila"), ("06", "Colima"), ("07", "Chiapas"),
    ("08", "Chihuahua"), ("09", "Ciudad de México"), ("10", "Durango"),
    ("11", "Guanajuato"), ("12", "Guerrero"), ("13", "Hidalgo"), ("14", "Jalisco"),
    ("15", "México"), ("16", "Michoacán"), ("17", "Morelos"), ("18", "Nayarit"),
    ("19", "Nuevo León"), ("20", "Oaxaca"), ("21", "Puebla"), ("22", "Querétaro"),
    ("23", "Quintana Roo"), ("24", "San Luis Potosí"), ("25", "Sinaloa"),
    ("26", "Sonora"), ("27", "Tabasco"), ("28", "Tamaulipas"), ("29", "Tlaxcala"),
    ("30", "Veracruz"), ("31", "Yucatán"), ("32", "Zacatecas"),
]


def fetch_regional(client: INEGIBIEClient, mapping: dict) -> dict:
    """Itera geo='01'-'32' para cada serie del mapping. Devuelve tabla por entidad.

    Espera mapping con: regional_modo=True, series_map={ID: nombre_columna}, periodo_format.
    Para cada entidad, captura el último valor de cada serie BIE.
    """
    fmt = mapping["periodo_format"]
    series_map = mapping["series_map"]
    out_rows = []
    for geo, entidad in ENTIDADES_GEO:
        row = {"Entidad": entidad, "_geo": geo}
        ultimo_periodo = None
        for bie_id, col in series_map.items():
            try:
                resp = client.get_indicator(bie_id, geo=geo, recent_only=False)
                rows = client.parse_series(resp)
                # Tomar el último valor numérico de la serie
                ult = None
                ult_per = None
                for r in reversed(rows):
                    try:
                        v = float(r["obs_value"])
                        ult = round(v, 2)
                        ult_per = r["time_period"]
                        break
                    except (TypeError, ValueError):
                        continue
                row[col] = ult
                if ult_per and not ultimo_periodo:
                    # detectar max_m
                    max_m = 0
                    for rr in rows:
                        tp = rr.get("time_period", "")
                        if "/" in tp:
                            parts = tp.split("/")
                            if len(parts) >= 2 and parts[1].isdigit():
                                max_m = max(max_m, int(parts[1]))
                    ultimo_periodo = to_periodo_local(ult_per, fmt, max_m_in_series=max_m)
            except Exception as e:
                print(f"    ERROR geo={geo} {bie_id}: {e}", file=sys.stderr)
                row[col] = None
        row["_periodo"] = ultimo_periodo
        out_rows.append(row)
        print(f"    {entidad:25s} | periodo={ultimo_periodo} | {len(series_map)} series")
    return {"entidades": out_rows, "periodo_referencia": ultimo_periodo}


def fetch_indicator(client: INEGIBIEClient, mapping: dict, geo: str = "00") -> dict[str, dict]:
    """Descarga todas las series del mapping. Devuelve {bie_id: [{periodo, valor}, ...]}.

    Combina por periodo en orden cronologico. Maneja float con redondeo a 2 decimales.
    """
    fmt = mapping["periodo_format"]
    out = {}
    for bie_id, col_name in mapping["series_map"].items():
        try:
            resp = client.get_indicator(bie_id, geo=geo, recent_only=False)
            rows = client.parse_series(resp)
        except Exception as e:
            print(f"    ERROR {bie_id} ({col_name}): {e}", file=sys.stderr)
            out[bie_id] = {"col": col_name, "rows": []}
            continue
        # Detectar formato trimestral: si max segundo componente <=4 es QQ directo, si >=6 es MM cierre
        max_m = 0
        for r in rows:
            tp = r.get("time_period", "")
            if "/" in tp:
                parts = tp.split("/")
                if len(parts) >= 2 and parts[1].isdigit():
                    max_m = max(max_m, int(parts[1]))
        parsed = []
        for r in rows:
            periodo = to_periodo_local(r["time_period"], fmt, max_m_in_series=max_m)
            if periodo is None:
                continue
            try:
                valor = round(float(r["obs_value"]), 2)
            except (TypeError, ValueError):
                valor = None
            parsed.append((periodo, valor))
        out[bie_id] = {"col": col_name, "rows": parsed}
        print(f"    {bie_id} -> {col_name}: {len(parsed)} obs ({parsed[-1][0] if parsed else 'sin datos'})")
    return out


def build_row_series(fetched: dict[str, dict]) -> tuple[list[str], list[dict[str, Any]]]:
    """Pivote a formato row-oriented. Devuelve (periodos_ordenados, filas)."""
    periodos = set()
    for d in fetched.values():
        for periodo, _ in d["rows"]:
            periodos.add(periodo)
    periodos_sorted = sorted(periodos, key=parse_periodo_for_sort)
    filas = []
    for periodo in periodos_sorted:
        fila = {"Periodo": periodo}
        for d in fetched.values():
            col = d["col"]
            valor = next((v for p, v in d["rows"] if p == periodo), None)
            fila[col] = valor
        filas.append(fila)
    return periodos_sorted, filas


def parse_periodo_for_sort(p: str) -> tuple:
    """Sort helper: maneja 'mmm-yy', 'TQ-yy', 'YYYY', 'QNN-yy'."""
    if "-" not in p and len(p) == 4:
        return (int(p),)
    parts = p.split("-")
    if len(parts) != 2:
        return (0, 0)
    head, yy = parts
    # cutoff: yy <= 30 -> 20XX, yy > 30 -> 19XX. Cubre 1931-2030.
    yyy = 2000 + int(yy) if int(yy) <= 30 else 1900 + int(yy)
    if head.lower() in MESES:
        return (yyy, MESES.index(head.lower()) + 1)
    if head.startswith("T"):
        return (yyy, int(head[1:]) * 3)
    if head.startswith("Q"):
        return (yyy, int(head[1:]))
    return (yyy, 0)


def merge_into_data(existing_path: Path, periodos: list[str], filas: list[dict],
                    series_cols: list[str]) -> dict:
    """Mezcla periodos+filas nuevos en data/{id}.json existente, preservando metadata.

    Sustituye totalmente periodos y series. Conserva todo lo demas.
    """
    if existing_path.exists():
        d = json.loads(existing_path.read_text(encoding="utf-8"))
    else:
        d = {"id": existing_path.stem, "series": [], "periodos": []}

    # Actualiza columnas si difieren (por agregar columnas BIE nuevas)
    cols_actuales = list(d.get("columnas_normalizadas", []))
    cols_nuevas = ["Periodo"] + series_cols
    if cols_actuales != cols_nuevas:
        d["columnas_normalizadas"] = cols_nuevas
        if "columnas" in d:
            d["columnas"] = cols_nuevas

    d["periodos"] = periodos
    d["series"] = filas
    d["ultima_actualizacion"] = date.today().isoformat()
    d["fuente_ingest"] = "BIE-INEGI"
    return d


def diff_summary(old_path: Path, new_data: dict) -> str:
    """Diff humano: cuántas filas nuevas, último valor antes/después."""
    if not old_path.exists():
        return f"  NUEVO. {len(new_data['periodos'])} periodos."
    old = json.loads(old_path.read_text(encoding="utf-8"))
    old_p = set(old.get("periodos", []))
    new_p = set(new_data["periodos"])
    nuevos = new_p - old_p
    perdidos = old_p - new_p
    out = []
    out.append(f"  Periodos: antes={len(old_p)}, despues={len(new_p)}, +{len(nuevos)}, -{len(perdidos)}")
    if nuevos:
        out.append(f"  Nuevos: {sorted(nuevos)[:5]}{'...' if len(nuevos) > 5 else ''}")
    # Comparar último periodo común
    common = old_p & new_p
    if common:
        ultimo = max(common, key=parse_periodo_for_sort)
        old_row = next((r for r in old.get("series", []) if r.get("Periodo") == ultimo or r.get("Mes") == ultimo), {})
        new_row = next((r for r in new_data["series"] if r.get("Periodo") == ultimo), {})
        cambios = []
        for k, v in new_row.items():
            if k == "Periodo":
                continue
            if k in old_row and old_row[k] != v:
                cambios.append(f"{k}: {old_row[k]} -> {v}")
        if cambios:
            out.append(f"  Cambios en {ultimo}: {'; '.join(cambios[:4])}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", default=None, help="Procesar solo un indicador")
    parser.add_argument("--dry-run", action="store_true", help="No escribe data/")
    parser.add_argument("--diff", action="store_true", help="Muestra diff vs actual")
    args = parser.parse_args(argv)

    load_env(ROOT)
    token = os.environ.get("INEGI_BIE_TOKEN")
    if not token:
        print("ERROR: falta INEGI_BIE_TOKEN", file=sys.stderr)
        return 2

    client = INEGIBIEClient(token=token)
    mapping_path = ROOT / "config" / "bie_mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

    indicadores = mapping["indicadores"]
    targets = [args.id] if args.id else list(indicadores.keys())

    rc = 0
    for iid in targets:
        if iid not in indicadores:
            print(f"[skip] {iid} no esta en bie_mapping.json")
            continue
        ind = indicadores[iid]
        if not ind.get("series_map"):
            print(f"[skip] {iid} sin series_map definido")
            continue
        # Indicadores que no son sub-mapping verificado, los marcamos como pendientes
        if not ind.get("_verificado") and not args.id:
            print(f"[skip] {iid} sin _verificado (usa --id {iid} para forzar)")
            continue

        print(f"\n=== {iid} ===")
        # Detectar modo regional
        if ind.get("regional_modo"):
            try:
                resultado = fetch_regional(client, ind)
            except Exception as e:
                print(f"  FAIL: {e}", file=sys.stderr)
                rc = 1
                continue
            existing = ROOT / "data" / f"{iid}.json"
            if existing.exists():
                d = json.loads(existing.read_text(encoding="utf-8"))
            else:
                d = {"id": iid}
            d["entidades"] = resultado["entidades"]
            d["periodo_referencia"] = resultado["periodo_referencia"]
            d["ultima_actualizacion"] = date.today().isoformat()
            d["fuente_ingest"] = "BIE-INEGI (regional iter geo)"
            # Mantener compatibilidad con normalize.build_tabular: pivote a filas
            cols_serie = ["Entidad"] + list(ind["series_map"].values())
            d["columnas"] = cols_serie
            d["columnas_normalizadas"] = cols_serie
            d["series"] = [
                {k: r.get(k) for k in cols_serie}
                for r in resultado["entidades"]
            ]
            # Sincronizar periodos con número de filas (validate exige len iguales)
            d["periodos"] = [resultado.get("periodo_referencia") or ""] * len(d["series"])
            if not args.dry_run:
                existing.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  -> escrito {existing.relative_to(ROOT)}")
            else:
                print(f"  [dry-run]")
            continue

        try:
            fetched = fetch_indicator(client, ind, geo=ind.get("geo", "00"))
        except Exception as e:
            print(f"  FAIL: {e}", file=sys.stderr)
            rc = 1
            continue
        periodos, filas = build_row_series(fetched)
        cols = [d["col"] for d in fetched.values()]
        existing = ROOT / "data" / f"{iid}.json"
        new_data = merge_into_data(existing, periodos, filas, cols)

        if args.diff:
            print(diff_summary(existing, new_data))

        if not args.dry_run:
            existing.write_text(json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  -> escrito {existing.relative_to(ROOT)}")
        else:
            print(f"  [dry-run] no se escribio")

    return rc


if __name__ == "__main__":
    sys.exit(main())
