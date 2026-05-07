"""Validador automático del pipeline indicadores_inegi.

Cinco capas de chequeo sobre los 29 indicadores:
    1. Integridad datos crudos        (data/<id>.json)
    2. Integridad post normalize      (normalize.load_all)
    3. Rangos plausibles por indicador (bounds económicos)
    4. Consistencia cross-page        (headline vs detail)
    5. Inspección HTML rendered       (site/*.html)

Uso:
    python scripts/validate.py
    python scripts/validate.py --severity warning   # filtra por severidad mínima
    python scripts/validate.py --layer 5            # corre solo una capa

Exit code:
    0 si solo hay warnings/info
    1 si hay errors (bloquea deploy)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from normalize import load_all  # noqa: E402

ROOT = SCRIPT_DIR.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
CFG_DIR = ROOT / "config"

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}

# Rangos plausibles por indicador (ultimo). None = sin chequeo.
BOUNDS = {
    "inpc_mensual":         (0, 15, "% var. anual"),
    "inpc_quincenal":       (0, 15, "% var. anual"),
    "inpp":                 (-5, 20, "% var. anual"),
    "inflacion_resumen":    (0, 15, "% var. anual"),
    "pib_anual":            (-15, 15, "% var. real"),
    "pib_trimestral":       (-15, 15, "% var. real"),
    "pib_por_actividad":    (-15, 15, "% var. real"),
    "igae":                 (-20, 15, "% var. real anual"),
    "actividad_industrial": (-20, 20, "% var. real anual"),
    "consumo_privado":      (-15, 15, "% var. real anual"),
    "fbcf":                 (-25, 25, "% var. real anual"),
    "balanza_comercial":    (-30, 30, "% var. anual exportaciones"),
    "ind_ciclicos":         (-5, 5, "diferencia mensual pts"),
    "emim":                 (-20, 20, "% var. real anual"),
    "enec":                 (-20, 20, "% var. real anual"),
    "comercio_mayoreo":     (-20, 20, "% var. real anual"),
    "comercio_menudeo":     (-20, 20, "% var. real anual"),
    "servicios":            (-20, 20, "% var. real anual"),
    "enoe_trimestral":      (1, 8, "% desocupación"),
    "confianza_consumidor": (-5, 5, "pp diferencia mensual"),
    "emoe_ipm":             (-5, 5, "pp diferencia mensual"),
    "emoe_iat":             (-5, 5, "pp diferencia mensual"),
    "emoe_ice":             (-5, 5, "pp diferencia mensual"),
    "autos_ligeros":        (-50, 50, "% var. anual"),
    "autos_pesados":        (-50, 50, "% var. anual"),
    "export_entidad":       (0, 50, "% participación entidad líder"),
    "igae_ioae_resumen":    None,
}


class IssueList:
    def __init__(self) -> None:
        self.issues: list[tuple[str, int, str, str]] = []

    def add(self, indic: str, capa: int, sev: str, msg: str) -> None:
        self.issues.append((indic, capa, sev, msg))

    def filter(self, min_sev: str = "info") -> list[tuple[str, int, str, str]]:
        threshold = SEV_ORDER[min_sev]
        return [i for i in self.issues if SEV_ORDER[i[2]] <= threshold]

    def count_by_sev(self) -> dict[str, int]:
        c = {"error": 0, "warning": 0, "info": 0}
        for _, _, sev, _ in self.issues:
            c[sev] += 1
        return c


# ---------- Capa 1: integridad datos crudos ----------

def capa1_datos_crudos(issues: IssueList) -> None:
    catalog_path = CFG_DIR / "indicators.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["indicadores"]
    ids_catalog = {m["id"] for m in catalog}

    existing = {f.stem for f in DATA_DIR.glob("*.json")} - {"catalog", "interpretations"}
    faltantes = ids_catalog - existing
    huerfanos = existing - ids_catalog

    for iid in sorted(faltantes):
        issues.add(iid, 1, "error", f"Catálogo declara {iid} pero no existe data/{iid}.json")
    for iid in sorted(huerfanos):
        issues.add(iid, 1, "warning", f"data/{iid}.json no está en catálogo indicators.json")

    for iid in sorted(existing & ids_catalog):
        f = DATA_DIR / f"{iid}.json"
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            issues.add(iid, 1, "error", f"JSON inválido: {e}")
            continue

        # series no vacía
        series = d.get("series") or []
        if not series:
            issues.add(iid, 1, "error", "series vacío")
            continue

        # fuente URL plausible
        fuente = d.get("fuente_url", "")
        if not fuente.startswith("http"):
            issues.add(iid, 1, "warning", f"fuente_url ausente o no http: {fuente!r}")

        # ultima_actualizacion reciente (dentro del último año)
        ua = d.get("ultima_actualizacion")
        if ua:
            try:
                u_date = datetime.strptime(ua, "%Y-%m-%d").date()
                if (date.today() - u_date).days > 365:
                    issues.add(iid, 1, "warning", f"ultima_actualizacion vieja: {ua}")
            except ValueError:
                issues.add(iid, 1, "warning", f"ultima_actualizacion formato inválido: {ua}")

        # Para indicadores con periodos y series temporales, longitudes deben coincidir
        periodos = d.get("periodos") or []
        if periodos and len(periodos) != len(series):
            issues.add(iid, 1, "error",
                       f"len(periodos)={len(periodos)} != len(series)={len(series)}")

        # columnas_normalizadas sin duplicados
        cols = d.get("columnas_normalizadas") or []
        if len(cols) != len(set(cols)):
            dups = [c for c in cols if cols.count(c) > 1]
            issues.add(iid, 1, "warning", f"columnas_normalizadas con duplicados: {set(dups)}")


# ---------- Capa 2: integridad post normalize ----------

def capa2_normalize(indicadores: dict, issues: IssueList) -> None:
    for iid, d in indicadores.items():
        tabular = d.get("tabular", False)
        if tabular:
            # Tabular: valida filas y columnas
            filas = d.get("filas") or []
            cols = d.get("columnas") or []
            if not filas:
                issues.add(iid, 2, "error", "tabular sin filas")
            if not cols:
                issues.add(iid, 2, "error", "tabular sin columnas")
            continue

        periodos = d.get("periodos") or []
        series = d.get("series") or {}
        ma12 = d.get("ma12") or []
        campo_def = d.get("campoDefaultLabel") or d.get("campoDefault")

        if not periodos:
            issues.add(iid, 2, "error", "periodos vacío post normalize")
        if campo_def and campo_def not in series:
            issues.add(iid, 2, "error",
                       f"campoDefault={campo_def!r} no está en series.keys()={list(series.keys())}")
        if periodos and ma12 and len(periodos) != len(ma12):
            issues.add(iid, 2, "error",
                       f"len(periodos)={len(periodos)} != len(ma12)={len(ma12)}")

        # Serie principal debe tener al menos 2 puntos para chart.
        if campo_def and campo_def in series:
            sp = series[campo_def]
            validos = [v for v in sp if v is not None]
            if len(validos) < 2:
                issues.add(iid, 2, "warning",
                           f"serie principal solo {len(validos)} punto válido, chart caerá a fallback")

        # ultimo coherente con serie principal
        if campo_def in series:
            sp = series[campo_def]
            last_valid = next((v for v in reversed(sp) if v is not None), None)
            ultimo = d.get("ultimo")
            if ultimo is not None and last_valid is not None and abs(ultimo - last_valid) > 0.01:
                issues.add(iid, 2, "error",
                           f"ultimo={ultimo} != last(series.{campo_def})={last_valid}")

        # proximaPub fecha en futuro si existe
        prox = (d.get("proximaPub") or {}).get("fecha")
        if prox and prox != "—":
            # fecha friendly "DD mmm YYYY"
            m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", prox)
            if not m:
                issues.add(iid, 2, "info", f"proximaPub.fecha formato inesperado: {prox}")


# ---------- Capa 3: rangos plausibles ----------

def capa3_rangos(indicadores: dict, issues: IssueList) -> None:
    for iid, d in indicadores.items():
        bounds = BOUNDS.get(iid)
        if bounds is None:
            continue
        lo, hi, unidad = bounds
        ultimo = d.get("ultimo")
        if ultimo is None:
            issues.add(iid, 3, "warning", f"ultimo es None (esperado {lo} a {hi} {unidad})")
            continue
        if ultimo < lo or ultimo > hi:
            issues.add(iid, 3, "warning",
                       f"ultimo={ultimo} fuera de rango esperado [{lo}, {hi}] {unidad}")


# ---------- Capa 4: consistencia cross-page ----------

def capa4_cross_page(indicadores: dict, issues: IssueList) -> None:
    index_path = SITE_DIR / "index.html"
    if not index_path.exists():
        issues.add("index", 4, "error", "site/index.html no existe. Corre build.py primero.")
        return

    soup_idx = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")

    # Extrae valores del resumen table (columna valor)
    valores_idx: dict[str, str] = {}
    for tr in soup_idx.select("tbody tr.interactive"):
        a = tr.select_one("td a")
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"indicador/([^.]+)\.html", href)
        if not m:
            continue
        iid = m.group(1)
        tds = tr.select("td")
        if len(tds) >= 4:
            valores_idx[iid] = tds[3].get_text(strip=True)

    # Compara con detail stat_valor
    for iid in indicadores:
        det = SITE_DIR / "indicador" / f"{iid}.html"
        if not det.exists():
            issues.add(iid, 4, "error", f"site/indicador/{iid}.html no existe")
            continue
        soup = BeautifulSoup(det.read_text(encoding="utf-8"), "html.parser")
        card = soup.select_one(".stat-card .valor")
        if not card:
            issues.add(iid, 4, "warning", "detail sin .stat-card .valor")
            continue
        detail_val = card.get_text(strip=True)
        idx_val = valores_idx.get(iid, "")

        # Normalize para comparar: quita %, pp, pts, MDD, espacios, separadores.
        def _clean(s: str) -> str:
            return re.sub(r"[%$,]|pp|pts|MDD|\s+", "", s).strip()

        if idx_val and detail_val and _clean(idx_val) != _clean(detail_val):
            # Tolerancia: en tabular, detail puede ser "Vista tabular" mientras index es "—"
            if "Vistatabular" in _clean(detail_val) and _clean(idx_val) in ("—", ""):
                continue
            issues.add(iid, 4, "warning",
                       f"valor index={idx_val!r} vs detail={detail_val!r}")


# ---------- Capa 5: inspección HTML rendered ----------

_UNDERSCORE_RAW = re.compile(r"\b[A-Z][a-zA-Z]*_[A-Za-z_]+\b")
_JINJA_LEAK = re.compile(r"\{\{[^}]+\}\}|\{%[^%]+%\}")
_TOKENS_BAD = ("None", "undefined", "NaN")


def capa5_html(indicadores: dict, issues: IssueList) -> None:
    htmls = list(SITE_DIR.glob("*.html")) + list((SITE_DIR / "indicador").glob("*.html"))
    for html_path in htmls:
        rel = html_path.relative_to(SITE_DIR)
        iid = html_path.stem if html_path.parent.name == "indicador" else "index"
        text = html_path.read_text(encoding="utf-8")

        # Jinja sin renderizar
        if _JINJA_LEAK.search(text):
            m = _JINJA_LEAK.search(text)
            issues.add(iid, 5, "error", f"{rel}: jinja sin renderizar: {m.group(0)[:60]!r}")

        # Tokens basura
        for tok in _TOKENS_BAD:
            if f">{tok}<" in text:
                issues.add(iid, 5, "warning", f"{rel}: token {tok!r} en body")

        # Underscore raw visible en tabla/headers (solo buscar en <th> y <h3>)
        soup = BeautifulSoup(text, "html.parser")
        for sel in ("th", "h3", ".label", ".nota"):
            for el in soup.select(sel):
                t = el.get_text(strip=True)
                # Excluir palabras naturales como Estados_Unidos, Baja_California (no aparecen así)
                # Detectar solo patrón CamelCase_SnakeCase típico de keys
                if _UNDERSCORE_RAW.search(t) and "Dif_" not in t:  # Dif_2025-2024_pp tolerado
                    issues.add(iid, 5, "info",
                               f"{rel}: posible key raw en <{sel}>: {t[:50]!r}")

        # Canvas huérfano sin page-data (solo detail)
        if html_path.parent.name == "indicador":
            has_canvas = bool(soup.select_one("canvas#detail-chart"))
            has_data = bool(soup.select_one("script#page-data"))
            if has_canvas and not has_data:
                issues.add(iid, 5, "error", f"{rel}: canvas sin page-data")

        # Links rotos a indicador inexistente
        valid_ids = set(indicadores.keys()) | {"__home__"}
        for a in soup.select("a"):
            href = a.get("href") or ""
            m = re.search(r"indicador/([^./]+)\.html", href)
            if m and m.group(1) not in indicadores:
                issues.add(iid, 5, "error", f"{rel}: link a indicador inexistente: {m.group(1)}")


# ---------- Capa 6: cobertura de interpretaciones ----------

def capa6_interpretaciones(indicadores: dict, issues: IssueList) -> None:
    interp_path = DATA_DIR / "interpretations.json"
    skip = {"catalog", "igae_ioae_resumen"}

    if not interp_path.exists():
        issues.add("interpretations", 6, "warning",
                   "data/interpretations.json no existe. Corre generate_interpretations.py")
        return

    try:
        raw = json.loads(interp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.add("interpretations", 6, "error", f"JSON inválido: {e}")
        return

    interps = {k: v for k, v in raw.items() if isinstance(v, dict) and "tipo" in v}
    ids_esperados = set(indicadores.keys()) - skip

    for iid in sorted(ids_esperados):
        block = interps.get(iid, {})
        tipo = block.get("tipo", "")
        if tipo == "pendiente" or not tipo:
            issues.add(iid, 6, "info", "Interpretación pendiente (sin tipo=auto)")
        elif tipo == "auto":
            modelo = block.get("modelo", "?")
            generado = block.get("generado_en", "?")
            basado_en = block.get("basado_en", "?")
            if not block.get("mensaje"):
                issues.add(iid, 6, "warning", "tipo=auto pero mensaje vacío")
            else:
                issues.add(iid, 6, "info",
                           f"OK · {modelo} · generado {generado} · basado en {basado_en}")

    auto_count = sum(1 for v in interps.values()
                     if isinstance(v, dict) and v.get("tipo") == "auto" and v.get("mensaje"))
    total = len(ids_esperados)
    issues.add("interpretations", 6, "info",
               f"Cobertura: {auto_count}/{total} indicadores con interpretación auto")


# ---------- Main ----------

def format_report(issues: IssueList, min_sev: str) -> str:
    filtered = issues.filter(min_sev)
    if not filtered:
        return "✓ Sin issues en nivel >= {}".format(min_sev)
    # Ordenar por severidad, capa, indicador
    filtered.sort(key=lambda x: (SEV_ORDER[x[2]], x[1], x[0]))
    lines = []
    lines.append(f"{'SEV':<8} {'CAPA':<5} {'INDICADOR':<28} MENSAJE")
    lines.append("-" * 110)
    for iid, capa, sev, msg in filtered:
        lines.append(f"{sev:<8} {capa:<5} {iid:<28} {msg}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--severity", default="info", choices=["error", "warning", "info"],
                   help="Severidad mínima a reportar")
    p.add_argument("--layer", type=int, choices=[1, 2, 3, 4, 5, 6],
                   help="Correr solo una capa (1-5)")
    args = p.parse_args()

    issues = IssueList()
    indicadores, _cal, _thr = load_all(ROOT)

    layers = [1, 2, 3, 4, 5, 6] if args.layer is None else [args.layer]

    if 1 in layers:
        capa1_datos_crudos(issues)
    if 2 in layers:
        capa2_normalize(indicadores, issues)
    if 3 in layers:
        capa3_rangos(indicadores, issues)
    if 4 in layers:
        capa4_cross_page(indicadores, issues)
    if 5 in layers:
        capa5_html(indicadores, issues)
    if 6 in layers:
        capa6_interpretaciones(indicadores, issues)

    print(format_report(issues, args.severity))
    counts = issues.count_by_sev()
    print()
    print(f"Resumen: {counts['error']} errors · {counts['warning']} warnings · {counts['info']} info")
    return 1 if counts["error"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
