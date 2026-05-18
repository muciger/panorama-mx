"""Recalcula composites derivados desde series base ya ingeridas.

Composites:
  - igae_ioae_resumen: IGAE por gran actividad (último periodo)
  - inflacion_resumen: INPC anual últimos 12 meses
  - pib_por_actividad: PIB trimestral primarias/secundarias/terciarias últimos 13 trim
  - pib_anual: variación real calculada desde volumen 2018 (BIE 782389)

Uso:
    python3 scripts/composites.py

Lee data/{base}.json y reescribe data/{composite}.json. Idempotente.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load(iid: str) -> dict | None:
    f = DATA / f"{iid}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _save(iid: str, d: dict) -> None:
    (DATA / f"{iid}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _last_value(rows: list, periodos: list, campo: str) -> tuple:
    """Devuelve (valor, periodo) último no-None del campo."""
    for i in range(len(rows) - 1, -1, -1):
        v = rows[i].get(campo)
        if v is not None:
            per = periodos[i] if i < len(periodos) else None
            return v, per
    return None, None


# ---------- igae_ioae_resumen ----------

def composite_igae_ioae_resumen() -> dict:
    """Tabla con IGAE por gran actividad: Total, Primarias, Secundarias, Terciarias.
    Muestra var. mensual y anual del último periodo."""
    raw = _load("igae")
    existing = _load("igae_ioae_resumen") or {}
    if not raw:
        return existing
    rows = raw.get("series", []) or []
    periodos = raw.get("periodos", []) or []
    if not rows:
        return existing

    conceptos = [
        ("Total", "Total_Mensual", "Total_Anual"),
        ("Actividades primarias", "Primarias_Mensual", "Primarias_Anual"),
        ("Actividades secundarias", "Secundarias_Mensual", "Secundarias_Anual"),
        ("Actividades terciarias", "Terciarias_Mensual", "Terciarias_Anual"),
    ]
    series_out = []
    ult_periodo_mensual = None
    ult_periodo_anual = None
    for nombre, k_mens, k_anual in conceptos:
        v_mens, p_mens = _last_value(rows, periodos, k_mens)
        v_anual, p_anual = _last_value(rows, periodos, k_anual)
        if ult_periodo_mensual is None and p_mens:
            ult_periodo_mensual = p_mens
        if ult_periodo_anual is None and p_anual:
            ult_periodo_anual = p_anual
        series_out.append({
            "Concepto": nombre,
            f"Var_mensual_{p_mens}": v_mens,
            f"Var_anual_{p_anual}": v_anual,
        })

    # Construir cols dinámicas
    cols = ["Concepto"]
    if ult_periodo_mensual:
        cols.append(f"Var_mensual_{ult_periodo_mensual}")
    if ult_periodo_anual:
        cols.append(f"Var_anual_{ult_periodo_anual}")

    out = {**existing}
    out["id"] = "igae_ioae_resumen"
    out["nombre"] = "IGAE por gran actividad económica (resumen)"
    out["categoria"] = "actividad"
    out["frecuencia"] = "mensual"
    out["unidad"] = "%"
    out["columnas"] = cols
    out["columnas_normalizadas"] = cols
    out["periodos"] = [ult_periodo_mensual] * len(series_out)
    out["series"] = series_out
    out["ultima_actualizacion"] = date.today().isoformat()
    out["fuente_ingest"] = "Composite derivado (igae)"
    return out


# ---------- inflacion_resumen ----------

def composite_inflacion_resumen() -> dict:
    """Últimos 12 meses INPC: variaciones anuales + mensual para chart.
    Construye _recuadros_inpc (3 paneles del comunicado) a partir de BIE.
    Preserva _cuadro1, _productos y _entidades_ciudades inyectados manualmente.
    """
    raw = _load("inpc_mensual")
    existing = _load("inflacion_resumen") or {}
    if not raw:
        return existing
    rows = raw.get("series", []) or []
    periodos = raw.get("periodos", []) or []
    if not rows or len(rows) < 12:
        return existing

    N = 12
    rows_short = rows[-N:]
    periodos_short = periodos[-N:]
    series_out = []
    for r, p in zip(rows_short, periodos_short):
        series_out.append({
            "Periodo": p,
            "INPC_anual": r.get("INPC_Anual"),
            "Subyacente_anual": r.get("Subyacente_Anual"),
            "No_subyacente_anual": r.get("No_subyacente_Anual"),
        })

    cols = ["Periodo", "INPC_anual", "Subyacente_anual", "No_subyacente_anual"]

    # _recuadros_inpc: 3 paneles cabecera del comunicado, construidos desde BIE
    ultimo = rows[-1]
    ultimo_per = periodos[-1]
    recuadros = {
        "periodo": ultimo_per,
        "componentes": [
            {
                "nombre": "Inflación general",
                "var_mensual": ultimo.get("INPC_Mensual"),
                "var_anual": ultimo.get("INPC_Anual"),
            },
            {
                "nombre": "Subyacente",
                "var_mensual": ultimo.get("Subyacente_Mensual"),
                "var_anual": ultimo.get("Subyacente_Anual"),
            },
            {
                "nombre": "No subyacente",
                "var_mensual": ultimo.get("No_subyacente_Mensual"),
                "var_anual": ultimo.get("No_subyacente_Anual"),
            },
        ],
    }

    # Actualizar filas BIE disponibles en _cuadro1 si ya existe inyectado
    existing_c1 = existing.get("_cuadro1") or {}
    if existing_c1 and existing_c1.get("periodo") == ultimo_per:
        # Ya está fresco; solo actualizar variaciones de las 7 filas BIE
        bie_vars = {
            "INPC":                         ("INPC_Mensual",                    "INPC_Anual"),
            "Subyacente":                   ("Subyacente_Mensual",              "Subyacente_Anual"),
            "Mercancías":                   ("Subyacente_mercancias_Mensual",   "Subyacente_mercancias_Anual"),
            "Servicios":                    ("Subyacente_servicios_Mensual",    "Subyacente_servicios_Anual"),
            "No subyacente":                ("No_subyacente_Mensual",           "No_subyacente_Anual"),
            "Agropecuarios":                ("No_subyacente_agropecuarios_Mensual", "No_subyacente_agropecuarios_Anual"),
            "Energéticos y tarifas autorizadas": ("No_subyacente_energeticos_Mensual", "No_subyacente_energeticos_Anual"),
        }
        for fila in existing_c1.get("filas", []):
            concepto = fila.get("concepto", "")
            if concepto in bie_vars:
                km, ka = bie_vars[concepto]
                if ultimo.get(km) is not None:
                    fila["var_mensual"] = ultimo[km]
                if ultimo.get(ka) is not None:
                    fila["var_anual"] = ultimo[ka]

    out = {**existing}
    out["id"] = "inflacion_resumen"
    out["nombre"] = "Inflación INPC general, subyacente y no subyacente"
    out["categoria"] = "precios"
    out["frecuencia"] = "mensual"
    out["unidad"] = "% var. anual"
    out["columnas"] = cols
    out["columnas_normalizadas"] = cols
    out["periodos"] = periodos_short
    out["series"] = series_out
    out["_recuadros_inpc"] = recuadros
    out["ultima_actualizacion"] = date.today().isoformat()
    out["fuente_ingest"] = "Composite derivado (inpc_mensual)"
    # Preservar claves inyectadas manualmente
    for key in ("_cuadro1", "_productos", "_entidades_ciudades"):
        if key in existing:
            out[key] = existing[key]
    return out


# ---------- pib_por_actividad ----------

def composite_pib_por_actividad() -> dict:
    """PIB últimos 16 trimestres con desglose sectorial completo (SCNM base 2018)."""
    raw = _load("pib_trimestral")
    existing = _load("pib_por_actividad") or {}
    if not raw:
        return existing
    rows = raw.get("series", []) or []
    periodos = raw.get("periodos", []) or []
    if not rows:
        return existing

    N = min(16, len(rows))
    rows_short = rows[-N:]
    periodos_short = periodos[-N:]
    series_out = []
    for r, p in zip(rows_short, periodos_short):
        series_out.append({
            "Trimestre": p,
            "Primarias_Anual":        r.get("Primarias_Anual"),
            "Secundarias_Anual":      r.get("Secundarias_Anual"),
            "Terciarias_Anual":       r.get("Terciarias_Anual"),
            "Mineria_Anual":          r.get("Mineria_Anual"),
            "Energia_agua_gas_Anual": r.get("Energia_agua_gas_Anual"),
            "Construccion_Anual":     r.get("Construccion_Anual"),
            "Manufacturas_Anual":     r.get("Manufacturas_Anual"),
            "Comercio_mayor_Anual":   r.get("Comercio_mayoreo_Anual"),
            "Comercio_menor_Anual":   r.get("Comercio_menudeo_Anual"),
            "Transportes_Anual":      r.get("Transportes_Anual"),
            "Financieros_Anual":      r.get("Servicios_financieros_Anual"),
            "Gubernamentales_Anual":  r.get("Actividades_gubernamentales_Anual"),
            # Legacy QoQ cols para compat con build.py
            "Primarias_Trim":         r.get("Primarias_Trimestral"),
            "Secundarias_Trim":       r.get("Secundarias_Trimestral"),
            "Terciarias_Trim":        r.get("Terciarias_Trimestral"),
        })

    cols = [
        "Trimestre",
        "Primarias_Anual", "Secundarias_Anual", "Terciarias_Anual",
        "Mineria_Anual", "Energia_agua_gas_Anual", "Construccion_Anual", "Manufacturas_Anual",
        "Comercio_mayor_Anual", "Comercio_menor_Anual", "Transportes_Anual",
        "Financieros_Anual", "Gubernamentales_Anual",
        "Primarias_Trim", "Secundarias_Trim", "Terciarias_Trim",
    ]
    out = {**existing}
    out["id"] = "pib_por_actividad"
    out["nombre"] = "PIB por actividad económica"
    out["categoria"] = "actividad"
    out["frecuencia"] = "trimestral"
    out["unidad"] = "% var. real"
    out["columnas"] = cols
    out["columnas_normalizadas"] = cols
    out["periodos"] = periodos_short
    out["series"] = series_out
    out["ultima_actualizacion"] = date.today().isoformat()
    out["fuente_ingest"] = "Composite derivado (pib_trimestral · SCNM+BIE)"
    return out


def composite_pib_trimestral_bie() -> None:
    """Complementa pib_trimestral.json con datos frescos del BIE.

    Estrategia:
    - Para periodos ya presentes en el JSON: solo actualiza columnas Trimestral/*_Trimestral
      con QoQ desestacionalizado del BIE (más preciso que QoQ raw de series originales).
    - Añade el periodo más reciente del BIE si no existe aún en el JSON
      (normalmente T1-XX cuando SCNM aún no publica el PIBT completo).
    - Las columnas Anual y sectoriales se respetan del JSON base (SCNM PIBT_2).
    """
    token = os.environ.get("INEGI_BIE_TOKEN")
    if not token:
        print("  [pib_bie] sin INEGI_BIE_TOKEN — omitido", file=sys.stderr)
        return

    existing = _load("pib_trimestral")
    if not existing:
        return

    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from bie.client import INEGIBIEClient
        client = INEGIBIEClient(token)

        def bie_to_periodo(p: str) -> str:
            year, q = p.split("/")
            return f"T{q}-{year[-2:]}"

        def fetch_map(sid: str) -> dict:
            resp = client.get_indicator(sid, recent_only=False)
            rows = client.parse_series(resp)
            return {bie_to_periodo(r["time_period"]): round(float(r["obs_value"]), 4)
                    for r in rows if r.get("obs_value") not in (None, "")}

        # Series anuales por actividad (para periodos nuevos)
        anual_map = {
            "Anual":           fetch_map("735904"),
            "Primarias_Anual": fetch_map("735907"),
            "Secundarias_Anual": fetch_map("735908"),
            "Terciarias_Anual":  fetch_map("735913"),
            "Mineria_Anual":           fetch_map("735909"),
            "Energia_agua_gas_Anual":  fetch_map("735910"),
            "Construccion_Anual":      fetch_map("735911"),
            "Manufacturas_Anual":      fetch_map("735912"),
            "Comercio_mayoreo_Anual":  fetch_map("735914"),
            "Comercio_menudeo_Anual":  fetch_map("735915"),
            "Transportes_Anual":       fetch_map("735916"),
            "Servicios_financieros_Anual":   fetch_map("735918"),
            "Servicios_inmobiliarios_Anual": fetch_map("735919"),
            "Servicios_profesionales_Anual": fetch_map("735920"),
            "Actividades_gubernamentales_Anual": fetch_map("735928"),
            # Demanda agregada (oferta y demanda global, árbol 605590)
            "Demanda_consumo_privado_Anual":  fetch_map("737475"),
            "Demanda_consumo_gobierno_Anual": fetch_map("737482"),
            "Demanda_FBCF_total_Anual":       fetch_map("737489"),
            "Demanda_FBCF_privada_Anual":     fetch_map("737503"),
            "Demanda_FBCF_publica_Anual":     fetch_map("737496"),
            "Demanda_export_byserv_Anual":    fetch_map("737517"),
            "Demanda_import_byserv_Anual":    fetch_map("737461"),
        }
        # Series QoQ desestacionalizadas
        qoq_map = {
            "Trimestral":            fetch_map("736185"),
            "Primarias_Trimestral":  fetch_map("736196"),
            "Secundarias_Trimestral": fetch_map("736203"),
            "Terciarias_Trimestral": fetch_map("736210"),
            "Demanda_consumo_privado_Trimestral":  fetch_map("737474"),
            "Demanda_consumo_gobierno_Trimestral": fetch_map("737481"),
            "Demanda_FBCF_total_Trimestral":       fetch_map("737488"),
            "Demanda_export_byserv_Trimestral":    fetch_map("737516"),
            "Demanda_import_byserv_Trimestral":    fetch_map("737460"),
        }

        series = existing.get("series", [])
        periodos = existing.get("periodos", [])
        periodos_set = set(periodos)

        # 1. Actualizar QoQ desest en periodos existentes
        for row in series:
            p = row["Periodo"]
            for col, pmap in qoq_map.items():
                if p in pmap:
                    row[col] = pmap[p]

        # 2. Añadir periodos nuevos presentes en BIE pero no en JSON
        all_bie_periodos = sorted(set(anual_map["Anual"].keys()) | set(qoq_map["Trimestral"].keys()))
        template_row = {k: None for k in series[0].keys()} if series else {}
        for p in all_bie_periodos:
            if p not in periodos_set:
                new_row = {**template_row, "Periodo": p}
                for col, pmap in {**anual_map, **qoq_map}.items():
                    new_row[col] = pmap.get(p)
                series.append(new_row)
                periodos.append(p)
                periodos_set.add(p)
                print(f"  [pib_bie] nuevo periodo: {p} · Anual={new_row.get('Anual')}%")

        # Recompute MA12
        anual_vals = [r.get("Anual") for r in series]
        ma12 = []
        for i in range(len(anual_vals)):
            window = [v for v in anual_vals[max(0, i - 11):i + 1] if v is not None]
            ma12.append(round(sum(window) / 12, 4) if len(window) == 12 else None)

        existing["series"] = series
        existing["periodos"] = periodos
        existing["benchmarks"] = {"ma12_Anual": ma12}
        existing["ultima_actualizacion"] = date.today().isoformat()
        existing["fuente_ingest"] = "SCNM_PIBT+BIE"
        _save("pib_trimestral", existing)
        print(f"  [pib_bie] pib_trimestral actualizado: {len(series)} periodos · último {periodos[-1]}")

    except Exception as e:
        print(f"  [pib_bie] ERROR: {e}", file=sys.stderr)


def composite_enoe_trimestral() -> dict:
    """Reconstruye tabla pivote ENOE trimestral T_prev vs T_actual desde serie ingestada.

    El ingest BIE escribe 21 columnas con series trimestrales (84 obs).
    Este composite genera la tabla pivote (Concepto × T_prev_Abs/T_actual_Abs/Dif/%
    que el normalize espera).

    Mantiene la serie completa en _serie_full para descarga CSV.
    """
    raw = _load("enoe_trimestral")
    if not raw:
        return {}
    rows = raw.get("series", []) or []
    periodos = raw.get("periodos", []) or []
    if not rows or len(rows) < 5:
        return raw
    # Detectar si ya está en formato pivote (idempotencia).
    # Pivote tiene 'Concepto' y al menos una clave que termina en '_Abs'.
    if rows and isinstance(rows[0], dict) and "Concepto" in rows[0]:
        if any(k.endswith("_Abs") for k in rows[0].keys()):
            return raw
    # Es serie temporal: tomar último T y mismo T año anterior (4 atrás)
    ult_idx = len(rows) - 1
    prev_idx = max(0, ult_idx - 4)
    ult = rows[ult_idx]
    prev = rows[prev_idx]
    p_ult = periodos[ult_idx]
    p_prev = periodos[prev_idx]

    def absV(r, k):
        v = r.get(k)
        return int(v) if v is not None else None

    def pct(num, den):
        if num is None or den is None or den == 0:
            return None
        return round(num / den * 100, 1)

    conceptos = []
    # Estructura: Total, luego sub-grupos PEA/PNEA, luego Hombres y Mujeres
    for sexo_nombre, suf in [("Total", "Total"), ("Hombres", "Hombres"), ("Mujeres", "Mujeres")]:
        pob = absV(ult, f"Pob_total_{suf}")
        pob_p = absV(prev, f"Pob_total_{suf}")
        pea = absV(ult, f"PEA_{suf}")
        pea_p = absV(prev, f"PEA_{suf}")
        ocup = absV(ult, f"PEA_ocupada_{suf}")
        ocup_p = absV(prev, f"PEA_ocupada_{suf}")
        deso = absV(ult, f"PEA_desocupada_{suf}")
        deso_p = absV(prev, f"PEA_desocupada_{suf}")
        pnea = absV(ult, f"PNEA_{suf}")
        pnea_p = absV(prev, f"PNEA_{suf}")
        disp = absV(ult, f"PNEA_disponible_{suf}")
        disp_p = absV(prev, f"PNEA_disponible_{suf}")
        nodi = absV(ult, f"PNEA_no_disponible_{suf}")
        nodi_p = absV(prev, f"PNEA_no_disponible_{suf}")
        # Header de sexo (Total no se prefija con espacio)
        if sexo_nombre == "Total":
            conceptos.append({"Concepto": "Total",
                              "T_prev_Abs": pob_p, "T_actual_Abs": pob,
                              "Dif_Abs": (pob - pob_p) if pob and pob_p else None,
                              "T_prev_Pct": 100.0, "T_actual_Pct": 100.0,
                              "Dif_pp": None})
        else:
            conceptos.append({"Concepto": sexo_nombre,
                              "T_prev_Abs": pob_p, "T_actual_Abs": pob,
                              "Dif_Abs": (pob - pob_p) if pob and pob_p else None,
                              "T_prev_Pct": pct(pob_p, absV(prev, "Pob_total_Total")),
                              "T_actual_Pct": pct(pob, absV(ult, "Pob_total_Total")),
                              "Dif_pp": None})
        # PEA
        conceptos.append({"Concepto": "  PEA",
                          "T_prev_Abs": pea_p, "T_actual_Abs": pea,
                          "Dif_Abs": (pea - pea_p) if pea and pea_p else None,
                          "T_prev_Pct": pct(pea_p, pob_p),
                          "T_actual_Pct": pct(pea, pob),
                          "Dif_pp": round(pct(pea, pob) - pct(pea_p, pob_p), 1) if pct(pea, pob) and pct(pea_p, pob_p) else None})
        conceptos.append({"Concepto": "    Ocupada",
                          "T_prev_Abs": ocup_p, "T_actual_Abs": ocup,
                          "Dif_Abs": (ocup - ocup_p) if ocup and ocup_p else None,
                          "T_prev_Pct": pct(ocup_p, pea_p),
                          "T_actual_Pct": pct(ocup, pea),
                          "Dif_pp": round(pct(ocup, pea) - pct(ocup_p, pea_p), 1) if pct(ocup, pea) and pct(ocup_p, pea_p) else None})
        conceptos.append({"Concepto": "    Desocupada",
                          "T_prev_Abs": deso_p, "T_actual_Abs": deso,
                          "Dif_Abs": (deso - deso_p) if deso and deso_p else None,
                          "T_prev_Pct": pct(deso_p, pea_p),
                          "T_actual_Pct": pct(deso, pea),
                          "Dif_pp": round(pct(deso, pea) - pct(deso_p, pea_p), 1) if pct(deso, pea) and pct(deso_p, pea_p) else None})
        # PNEA
        conceptos.append({"Concepto": "  PNEA",
                          "T_prev_Abs": pnea_p, "T_actual_Abs": pnea,
                          "Dif_Abs": (pnea - pnea_p) if pnea and pnea_p else None,
                          "T_prev_Pct": pct(pnea_p, pob_p),
                          "T_actual_Pct": pct(pnea, pob),
                          "Dif_pp": round(pct(pnea, pob) - pct(pnea_p, pob_p), 1) if pct(pnea, pob) and pct(pnea_p, pob_p) else None})
        conceptos.append({"Concepto": "    Disponible",
                          "T_prev_Abs": disp_p, "T_actual_Abs": disp,
                          "Dif_Abs": (disp - disp_p) if disp and disp_p else None,
                          "T_prev_Pct": pct(disp_p, pnea_p),
                          "T_actual_Pct": pct(disp, pnea),
                          "Dif_pp": round(pct(disp, pnea) - pct(disp_p, pnea_p), 1) if pct(disp, pnea) and pct(disp_p, pnea_p) else None})
        conceptos.append({"Concepto": "    No disponible",
                          "T_prev_Abs": nodi_p, "T_actual_Abs": nodi,
                          "Dif_Abs": (nodi - nodi_p) if nodi and nodi_p else None,
                          "T_prev_Pct": pct(nodi_p, pnea_p),
                          "T_actual_Pct": pct(nodi, pnea),
                          "Dif_pp": round(pct(nodi, pnea) - pct(nodi_p, pnea_p), 1) if pct(nodi, pnea) and pct(nodi_p, pnea_p) else None})

    # Renombrar columnas con periodos reales
    cols_renamed = {
        "T_prev_Abs": f"{p_prev}_Abs",
        "T_actual_Abs": f"{p_ult}_Abs",
        "Dif_Abs": f"Dif_{p_ult}-{p_prev}_Abs",
        "T_prev_Pct": p_prev,
        "T_actual_Pct": p_ult,
        "Dif_pp": f"Dif_{p_ult}-{p_prev}_pp",
    }
    rows_renamed = []
    for c in conceptos:
        new_row = {"Concepto": c["Concepto"]}
        for old_k, new_k in cols_renamed.items():
            new_row[new_k] = c.get(old_k)
        rows_renamed.append(new_row)

    cols_final = ["Concepto"] + list(cols_renamed.values())

    out = {**raw}
    out["columnas"] = cols_final
    out["columnas_normalizadas"] = cols_final
    out["periodos"] = [c["Concepto"] for c in conceptos]
    out["series"] = rows_renamed
    out["ultima_actualizacion"] = date.today().isoformat()
    out["fuente_ingest"] = f"BIE-INEGI 21 series ENOE trimestral, pivote T={p_ult} vs T={p_prev}"
    out["_periodo_actual"] = p_ult
    out["_periodo_prev"] = p_prev
    return out


def composite_pib_anual() -> dict:
    """PIB anual variación real calculada desde volumen base 2018 (BIE 782389)."""
    existing = _load("pib_anual") or {}
    # Cargar .env y consultar BIE
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()
    if "INEGI_BIE_TOKEN" not in os.environ:
        return existing
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from bie.client import INEGIBIEClient
        c = INEGIBIEClient(token=os.environ["INEGI_BIE_TOKEN"])
        resp = c.get_indicator("782389", geo="00")
        rows = c.parse_series(resp)
    except Exception as e:
        print(f"  pib_anual fallback: {e}", file=sys.stderr)
        return existing

    parsed = []
    for r in rows:
        try:
            anio = int(r["time_period"])
            valor = float(r["obs_value"])
            parsed.append((anio, valor))
        except (TypeError, ValueError):
            continue
    parsed.sort()
    series_out = []
    periodos_out = []
    for i, (anio, val) in enumerate(parsed):
        if i == 0:
            continue
        prev = parsed[i - 1][1]
        if prev > 0:
            var = (val / prev - 1) * 100
            series_out.append({"Periodo": str(anio), "PIB_anual": round(var, 2)})
            periodos_out.append(str(anio))

    cols = ["Periodo", "PIB_anual"]
    out = {**existing}
    out["id"] = "pib_anual"
    out["nombre"] = "PIB anual a precios constantes (resumen)"
    out["categoria"] = "actividad"
    out["frecuencia"] = "anual"
    out["unidad"] = "% var. real"
    out["columnas"] = cols
    out["columnas_normalizadas"] = cols
    out["periodos"] = periodos_out
    out["series"] = series_out
    out["ultima_actualizacion"] = date.today().isoformat()
    out["fuente_ingest"] = "BIE-INEGI 782389 (calculo de variacion desde volumen 2018)"
    return out


# ---------- main ----------

def main() -> int:
    # composite_pib_trimestral_bie escribe directamente; corre antes de los demás PIB
    try:
        composite_pib_trimestral_bie()
    except Exception as e:
        print(f"  WARN composite_pib_trimestral_bie: {e}", file=sys.stderr)

    composites = [
        ("igae_ioae_resumen", composite_igae_ioae_resumen),
        ("inflacion_resumen", composite_inflacion_resumen),
        ("pib_por_actividad", composite_pib_por_actividad),
        ("pib_anual", composite_pib_anual),
        ("enoe_trimestral", composite_enoe_trimestral),
    ]
    for iid, fn in composites:
        try:
            d = fn()
            if d:
                _save(iid, d)
                rows = len(d.get("series", []) or d.get("filas", []) or [])
                ult = d.get("periodos", ["—"])[-1] if d.get("periodos") else "—"
                print(f"  composite {iid}: {rows} filas, último {ult}")
            else:
                print(f"  [skip] {iid} no se pudo recalcular (base ausente)")
        except Exception as e:
            print(f"  ERROR {iid}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
