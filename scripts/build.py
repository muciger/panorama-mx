"""Genera site/ estático a partir de data/*.json + config/*.json + templates/*.j2.

Uso:
    python scripts/build.py

Output:
    site/index.html
    site/indicador/<id>.html  (uno por los 29 indicadores)
    site/assets/styles.css
    site/assets/app.js

Chart.js se carga desde CDN en base.html.j2.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build")
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Permitir import relativo al correr como script
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from normalize import load_all  # noqa: E402

ROOT = SCRIPT_DIR.parent
TEMPLATES_DIR = ROOT / "templates"
ASSETS_DIR = ROOT / "assets"
SITE_DIR = ROOT / "site"

BUILD_LABEL = "Tablero mensual · v1"
BUILD_CHIP = "v1"
TOPBAR_TITLE = "Indicadores económicos México"


def _hoy_mx() -> date:
    """'Hoy' en horario del centro de México. El runner cloud corre en UTC; sin
    esto, desde ~18:00 CST el build creería que ya es mañana y correría la
    etiqueta de semana y el límite lun/mar del reporte un día."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Mexico_City")).date()
    except Exception:
        return date.today()


def _json_for_script(obj: Any) -> str:
    """Serializa a JSON seguro para incrustar en <script>. json.dumps no escapa
    '<' '>' '/', así que un valor con '</script>' cerraría el bloque e inyectaría
    HTML/JS (XSS). Escapamos la secuencia de cierre y los separadores Unicode.
    Sigue siendo JSON válido: JSON.parse revierte el escape."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace(chr(0x2028), "\\u2028")
        .replace(chr(0x2029), "\\u2029")
    )

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
DIAS_ES_ABR = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

ALERTA_LABEL = {"verde": "OK", "amarillo": "Vigilar", "rojo": "Atención", "neutro": "Sin umbral"}

NAV_STRUCTURE = [
    ("Inicio", [("__home__", "▦ Vista general", "index.html")]),
    ("Resúmenes", [
        ("pib_anual", "PIB anual (resumen)", "indicador/pib_anual.html"),
        ("inflacion_resumen", "Inflación (resumen)", "indicador/inflacion_resumen.html"),
        ("igae_ioae_resumen", "IGAE/IOAE por sector", "indicador/igae_ioae_resumen.html"),
    ]),
    ("Macro", [
        ("pib_trimestral", "PIB trimestral", "indicador/pib_trimestral.html"),
        ("pib_por_actividad", "PIB por actividad", "indicador/pib_por_actividad.html"),
    ]),
    ("Actividad", [
        ("igae", "IGAE", "indicador/igae.html"),
        ("actividad_industrial", "Actividad industrial", "indicador/actividad_industrial.html"),
        ("consumo_privado", "Consumo privado", "indicador/consumo_privado.html"),
        ("fbcf", "FBCF", "indicador/fbcf.html"),
        ("balanza_comercial", "Balanza comercial", "indicador/balanza_comercial.html"),
        ("ind_ciclicos", "Indicadores cíclicos", "indicador/ind_ciclicos.html"),
    ]),
    ("Encuestas sectoriales", [
        ("emim", "EMIM manufactura", "indicador/emim.html"),
        ("enec", "ENEC construcción", "indicador/enec.html"),
        ("comercio_mayoreo", "Comercio mayoreo", "indicador/comercio_mayoreo.html"),
        ("comercio_menudeo", "Comercio menudeo", "indicador/comercio_menudeo.html"),
        ("servicios", "Servicios", "indicador/servicios.html"),
    ]),
    ("Precios", [
        ("inpc_mensual", "INPC mensual", "indicador/inpc_mensual.html"),
        ("inpc_quincenal", "INPC quincenal", "indicador/inpc_quincenal.html"),
        ("inpp", "INPP", "indicador/inpp.html"),
    ]),
    ("Empleo", [
        ("enoe_trimestral", "ENOE trimestral", "indicador/enoe_trimestral.html"),
        ("enoe_mensual", "ENOE mensual", "indicador/enoe_mensual.html"),
        # empleo_imss vive como sección dedicada del sidebar (imss_explorador.html)
    ]),
    ("Automotriz", [
        ("autos_ligeros", "Vehículos ligeros", "indicador/autos_ligeros.html"),
        ("autos_pesados", "Vehículos pesados", "indicador/autos_pesados.html"),
    ]),
    ("Regional", [
        ("export_entidad", "Exportaciones entidad", "indicador/export_entidad.html"),
    ]),
    ("Sentimiento", [
        ("confianza_consumidor", "Confianza consumidor", "indicador/confianza_consumidor.html"),
        ("emoe_ipm", "EMOE IPM", "indicador/emoe_ipm.html"),
        ("emoe_iat", "EMOE IAT", "indicador/emoe_iat.html"),
        ("emoe_ice", "EMOE ICE", "indicador/emoe_ice.html"),
    ]),
]

HEADLINE_CFG = [
    {"id": "inpc_mensual", "label": "Inflación INPC",
     "footer_tmpl": "MA12: {ma12}% · Objetivo Banxico 3% ±1pp"},
    {"id": "igae", "label": "IGAE actividad",
     "footer_tmpl": "MA12: {ma12}% · Umbral crecimiento 2% anual"},
    {"id": "balanza_comercial", "label": "Exportaciones",
     "footer_tmpl": "MA12: {ma12}% · Crecimiento anual"},
    {"id": "confianza_consumidor", "label": "Confianza consumidor",
     "footer_tmpl": "MA12: {ma12}pp · Umbral ±1pp mensual"},
    {"id": "enoe_trimestral", "label": "Desocupación ENOE",
     "footer_tmpl": "T4 2025 · Tasa de desocupación trimestral"},
]


# ------------- helpers -------------

def fmt_num(v: float | None, unit: str = "", signed: bool = False) -> str:
    if v is None:
        return "—"
    sign = "+" if (signed and v > 0) else ""
    return f"{sign}{v:.1f}{unit}"


def fmt_hoy_label(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} {MESES[d.month - 1]} {d.year}"


def fmt_fecha_friendly(iso: str) -> str:
    y, m, day = iso.split("-")
    return f"{int(day)} {MESES[int(m) - 1]} {y}"


def build_calendar_context(calendar: dict, indicadores: dict, hoy: date) -> dict:
    """Arma hoy/proximas publicaciones y etiquetas ultima_pub/prox_pub para el topbar."""
    hoy_iso = hoy.isoformat()
    hoy_list: list[dict] = []
    todos: list[tuple[str, str, str]] = []  # (fecha_iso, indic_id, evento_short)

    for iid, cal in calendar.items():
        for p in cal.get("proximas_publicaciones", []) or []:
            fecha = p["fecha"]
            evento = p.get("evento_ics", "")
            short = evento.split(".")[0].strip()[:60]
            if fecha == hoy_iso:
                indic = indicadores.get(iid, {})
                ultimo = indic.get("ultimo")
                unidad = indic.get("unidad", "")
                preview = f"{indic.get('_label_tabla', iid)}: {ultimo}{unidad}" if ultimo is not None else short
                hoy_list.append({
                    "id": iid,
                    "indicador": indic.get("nombre", iid),
                    "periodo": "publicación hoy",
                    "hora": "07:00",
                    "preview": preview,
                    "esNuevo": True,
                })
            elif fecha > hoy_iso:
                todos.append((fecha, iid, short))

    todos.sort(key=lambda x: x[0])
    proximas = []
    for fecha, iid, short in todos[:3]:
        y, m, d = fecha.split("-")
        weekday = datetime.strptime(fecha, "%Y-%m-%d").weekday()
        fecha_label = f"{DIAS[weekday]} {int(d)} {MESES[int(m) - 1]}"
        proximas.append({
            "fecha": fecha_label,
            "indicador": indicadores.get(iid, {}).get("_label_tabla") or short,
            "periodo": "",
            "id": iid,
        })

    # Última publicación: máx fecha_ultima_pub entre indicadores
    ultimas = []
    for cal in calendar.values():
        u = cal.get("ultima_publicacion_ics") or {}
        if u.get("fecha"):
            ultimas.append(u["fecha"])
    ultima_pub = fmt_fecha_friendly(max(ultimas)) if ultimas else "—"

    prox_pub = f"{proximas[0]['indicador']} · {proximas[0]['fecha']}" if proximas else "—"

    return {
        "hoy_label": fmt_hoy_label(hoy),
        "hoy": hoy_list,
        "proximas": proximas,
        "ultima_pub": ultima_pub,
        "prox_pub": prox_pub,
    }


# ------------- builders de contexto por vista -------------

def build_headline(d: dict, cfg: dict) -> dict:
    delta = d.get("delta")
    if delta is None:
        cls, sym, txt = "flat", "≈", "—"
    elif delta > 0:
        cls, sym, txt = "up", "▲", f"+{delta:.1f} pp"
    elif delta < 0:
        cls, sym, txt = "down", "▼", f"{delta:.1f} pp"
    else:
        cls, sym, txt = "flat", "≈", "0.0 pp"

    tabular = d.get("tabular", False)
    periodos = d.get("periodos") or []
    if tabular:
        periodo = d.get("_periodo_tabular") or "—"
        previo_label = d.get("_previo_label_tabular") or ""
    else:
        periodo = periodos[-1] if periodos else "—"
        previo_label = f"vs {periodos[-2]}" if len(periodos) > 1 else ""
    ma12_ult = d.get("ma12_ult")
    ma12_fmt = f"{ma12_ult:.1f}" if ma12_ult is not None else "—"

    footer = cfg["footer_tmpl"].format(ma12=ma12_fmt)

    valor = d.get("ultimo")
    return {
        "id": cfg["id"],
        "label": cfg["label"],
        "alerta": d.get("alerta", "neutro"),
        "alerta_label": ALERTA_LABEL.get(d.get("alerta", "neutro"), "—"),
        "periodo": periodo,
        "valor_fmt": f"{valor:.1f}" if valor is not None else "—",
        "unidad": d.get("unidad", ""),
        "delta_cls": cls,
        "delta_sym": sym,
        "delta_txt": txt,
        "previo_label": previo_label,
        "footer": footer,
        "series": (d.get("series") or {}).get(d.get("campoDefaultLabel") or d.get("campoDefault")) if not tabular else [],
    }


def build_resumen_row(d: dict) -> dict:
    delta = d.get("delta")
    if delta is None:
        cls, txt = "flat", "—"
    elif delta > 0:
        cls, txt = "pos", f"+{delta:.1f}pp"
    elif delta < 0:
        cls, txt = "neg", f"{delta:.1f}pp"
    else:
        cls, txt = "flat", "0.0pp"

    valor = d.get("ultimo")
    ma12 = d.get("ma12_ult")
    tabular = d.get("tabular", False)
    periodos = d.get("periodos") or []
    periodo = d.get("_periodo_tabular", "—") if tabular else (periodos[-1] if periodos else "—")

    return {
        "id": d["id"],
        "nombre": d.get("_label_tabla") or d.get("nombre", d["id"]),
        "cat": d.get("categoria", "—"),
        "periodo": periodo,
        "valor_fmt": f"{valor:.1f}" if valor is not None else "—",
        "delta_cls": cls,
        "delta_txt": txt,
        "ma12_txt": f"{ma12:.1f}" if ma12 is not None else "—",
        "alerta": d.get("alerta", "neutro"),
        "alerta_label": ALERTA_LABEL.get(d.get("alerta", "neutro"), "—"),
    }


def _fmt_inegi_delta(v: float | None, unidad: str) -> dict:
    """Formato compacto para tile delta estilo INEGI: ▲ 0.1 pp / ▼ -1.0 pp."""
    if v is None:
        return {"valor": None, "fmt": "—", "arrow": "", "dir": "flat"}
    if v > 0.05:
        arrow, direccion = "▲", "up"
        signo = "+"
    elif v < -0.05:
        arrow, direccion = "▼", "down"
        signo = ""
    else:
        arrow, direccion = "—", "flat"
        signo = ""
    unidad_delta = "pp" if unidad == "%" else (unidad or "")
    return {
        "valor": v,
        "fmt": f"{signo}{v:.1f} {unidad_delta}".strip(),
        "arrow": arrow,
        "dir": direccion,
    }


def _detect_inegi_row_values(last: dict, campo_default: str | None = None) -> dict:
    """Lee el último row y extrae valor principal, delta mensual/trimestral y delta anual.
    Maneja varios layouts de indicadores INEGI."""

    # Usar campoDefault solo si NO termina en sufijos estándar (que tienen layouts dedicados).
    if campo_default and isinstance(last.get(campo_default), (int, float)):
        sufijos_std = ("_Anual", "_Mensual", "_anual", "_mensual", "_Trimestral", "_Nivel")
        if not any(campo_default.endswith(s) for s in sufijos_std) and campo_default not in ("Total", "Anual", "Mensual", "Trimestral"):
            # Indicador con varios campos sin sufijo estándar (autos: Ventas/Producción/Exportación).
            return {"nivel": None, "nivel_key": None,
                    "mensual": None, "anual": last[campo_default], "trimestral": None}

    # Layout A: <X>_Nivel + Mensual + Anual (Confianza Consumidor)
    for k, v in last.items():
        if k.endswith("_Nivel") and isinstance(v, (int, float)):
            return {"nivel": v, "nivel_key": k,
                    "mensual": last.get("Mensual") if isinstance(last.get("Mensual"), (int, float)) else None,
                    "anual": last.get("Anual") if isinstance(last.get("Anual"), (int, float)) else None,
                    "trimestral": None}

    # Layout B: Total simple (IMSS, donde Total es nivel grande)
    if isinstance(last.get("Total"), (int, float)) and not isinstance(last.get("Total_Anual"), (int, float)):
        return {"nivel": last["Total"], "nivel_key": "Total",
                "mensual": None, "anual": None, "trimestral": None}

    # Layout C: Total_Anual + Total_Mensual (IGAE, actividad industrial)
    if isinstance(last.get("Total_Anual"), (int, float)):
        return {"nivel": None, "nivel_key": None,
                "mensual": last.get("Total_Mensual") if isinstance(last.get("Total_Mensual"), (int, float)) else None,
                "anual": last["Total_Anual"], "trimestral": None}

    # Layout D: Trimestral + Anual sin Total_* (PIB)
    if isinstance(last.get("Anual"), (int, float)) or isinstance(last.get("Trimestral"), (int, float)):
        return {"nivel": None, "nivel_key": None,
                "mensual": None,
                "trimestral": last.get("Trimestral") if isinstance(last.get("Trimestral"), (int, float)) else None,
                "anual": last.get("Anual") if isinstance(last.get("Anual"), (int, float)) else None}

    # Layout E: campo terminado en _anual/_Anual (Inflación: INPC_anual)
    for k, v in last.items():
        if k.lower().endswith("_anual") and isinstance(v, (int, float)):
            mensual_key = k.replace("_anual", "_mensual").replace("_Anual", "_Mensual")
            return {"nivel": None, "nivel_key": None,
                    "mensual": last.get(mensual_key) if isinstance(last.get(mensual_key), (int, float)) else None,
                    "anual": v, "trimestral": None}

    # Layout F: campo único numérico (último recurso)
    for k, v in last.items():
        if k in ("Periodo", "Mes"):
            continue
        if isinstance(v, (int, float)):
            return {"nivel": None, "nivel_key": None,
                    "mensual": None, "anual": v, "trimestral": None}

    return {"nivel": None, "nivel_key": None, "mensual": None, "anual": None, "trimestral": None}


def _build_inegi_strip_imss(d: dict, raw: dict) -> dict | None:
    """Strip especial para empleo_imss: total puestos + ∆ mensual + ∆ anual."""
    rows = raw.get("series", []) or []
    if len(rows) < 13:
        return None
    last = rows[-1]
    total = last.get("Total")
    if not isinstance(total, (int, float)):
        return None
    periodo = last.get("Periodo") or last.get("Mes") or "—"
    # Calcular delta mensual y anual con datos previos
    prev_mes = rows[-2].get("Total") if len(rows) >= 2 else None
    prev_anio = rows[-13].get("Total") if len(rows) >= 13 else None
    delta_mes = (total - prev_mes) / 1000 if isinstance(prev_mes, (int, float)) else None  # en miles
    delta_anio = (total - prev_anio) / 1000 if isinstance(prev_anio, (int, float)) else None

    tiles = [{
        "head": "Empleo formal IMSS",
        "period": periodo,
        "value_fmt": f"{total/1_000_000:.2f} M puestos",
        "dir": "flat", "arrow": "",
    }]
    if delta_mes is not None:
        dirm = "up" if delta_mes > 0.5 else ("down" if delta_mes < -0.5 else "flat")
        arrow = "▲" if dirm == "up" else ("▼" if dirm == "down" else "—")
        tiles.append({
            "head": "Variación mensual",
            "period": periodo,
            "value_fmt": f"{'+' if delta_mes > 0 else ''}{delta_mes:,.0f} mil",
            "dir": dirm, "arrow": arrow,
        })
    if delta_anio is not None:
        dira = "up" if delta_anio > 0.5 else ("down" if delta_anio < -0.5 else "flat")
        arrow = "▲" if dira == "up" else ("▼" if dira == "down" else "—")
        tiles.append({
            "head": "Variación anual",
            "period": periodo,
            "value_fmt": f"{'+' if delta_anio > 0 else ''}{delta_anio:,.0f} mil",
            "dir": dira, "arrow": arrow,
        })
    return {"tiles": tiles, "indicador_corto": "Empleo IMSS"}


def build_inegi_strip(d: dict, iid: str) -> dict | None:
    """Datos para el bloque INEGI-style (tiles + headline).
    Detecta layout del indicador (nivel puro, variación pura, nivel+variaciones).
    Devuelve None si tabular sin layout especial o sin datos."""
    data_path = ROOT / "data" / f"{iid}.json"
    if not data_path.exists():
        return None
    try:
        raw = json.loads(data_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    # Strips especiales para indicadores que normalize marca tabular pero sí merecen header INEGI.
    if iid == "empleo_imss":
        return _build_inegi_strip_imss(d, raw)

    if d.get("tabular"):
        return None
    unidad = (d.get("unidad") or "").strip()
    periodos = d.get("periodos") or []
    ultimo_per = periodos[-1] if periodos else "—"
    campo_default = d.get("campoDefault")

    rows = raw.get("series", []) or []
    if not rows or not isinstance(rows[-1], dict):
        return None
    last = rows[-1]
    if isinstance(last.get("Periodo"), str):
        ultimo_per = last["Periodo"]
    elif isinstance(last.get("Mes"), str):
        ultimo_per = last["Mes"]

    vals = _detect_inegi_row_values(last, campo_default)
    short = d.get("nombre_corto") or _siglas_indicador(iid, d.get("nombre", ""))

    # Unidad para el primer tile (cuando hay nivel).
    nivel_fmt = None
    if vals["nivel"] is not None:
        if vals["nivel_key"] == "Total" and "puestos" in unidad.lower():
            unidad_nivel = " puestos"
        elif "_nivel" in (vals["nivel_key"] or "").lower() or "puntos" in unidad.lower():
            unidad_nivel = " pts"
        elif "MDD" in unidad:
            unidad_nivel = " MDD"
        else:
            unidad_nivel = ""
        nivel_fmt = (
            f"{vals['nivel']:,.0f}{unidad_nivel}" if abs(vals["nivel"]) >= 1000 else f"{vals['nivel']:.1f}{unidad_nivel}"
        )

    tiles = []
    es_porcentaje = ("%" in unidad) or "variación" in unidad.lower()

    if vals["nivel"] is not None:
        tiles.append({
            "head": short, "period": ultimo_per, "value_fmt": nivel_fmt, "dir": "flat", "arrow": "",
        })
        if vals["mensual"] is not None:
            m = _fmt_inegi_delta(vals["mensual"], "puntos" if "pts" in (nivel_fmt or "") else unidad)
            tiles.append({
                "head": "Variación mensual", "period": ultimo_per,
                "value_fmt": m["fmt"], "dir": m["dir"], "arrow": m["arrow"],
            })
        if vals["anual"] is not None:
            a = _fmt_inegi_delta(vals["anual"], "puntos" if "pts" in (nivel_fmt or "") else unidad)
            tiles.append({
                "head": "Variación anual", "period": ultimo_per,
                "value_fmt": a["fmt"], "dir": a["dir"], "arrow": a["arrow"],
            })
    else:
        # Variaciones puras: anual + (mensual o trimestral)
        if vals["anual"] is not None:
            v = vals["anual"]
            dirA = "up" if v > 0.05 else ("down" if v < -0.05 else "flat")
            tiles.append({
                "head": "Variación anual", "period": ultimo_per,
                "value_fmt": f"{'+' if v > 0 else ''}{v:.1f}%",
                "dir": dirA,
                "arrow": "▲" if dirA == "up" else ("▼" if dirA == "down" else "—"),
            })
        if vals["trimestral"] is not None:
            m = _fmt_inegi_delta(vals["trimestral"], "%")
            tiles.append({
                "head": "Variación trimestral", "period": ultimo_per,
                "value_fmt": m["fmt"], "dir": m["dir"], "arrow": m["arrow"],
            })
        elif vals["mensual"] is not None:
            m = _fmt_inegi_delta(vals["mensual"], "%")
            tiles.append({
                "head": "Variación mensual", "period": ultimo_per,
                "value_fmt": m["fmt"], "dir": m["dir"], "arrow": m["arrow"],
            })

    if not tiles:
        return None

    return {"tiles": tiles, "indicador_corto": short}


def _siglas_indicador(iid: str, nombre: str) -> str:
    """Devuelve un identificador corto para usar en el tile principal."""
    mapeo = {
        "igae": "IGAE",
        "inpc_mensual": "INPC",
        "inpc_quincenal": "INPC quincenal",
        "inpp": "INPP",
        "fbcf": "FBCF",
        "pib_trimestral": "PIB trimestral",
        "pib_anual": "PIB anual",
        "pib_por_actividad": "PIB por actividad",
        "balanza_comercial": "Balanza comercial",
        "empleo_imss": "Empleo IMSS",
        "enoe_mensual": "ENOE mensual",
        "enoe_trimestral": "ENOE trimestral",
        "actividad_industrial": "Actividad industrial",
        "consumo_privado": "Consumo privado",
        "confianza_consumidor": "ICC",
        "inflacion_resumen": "Inflación",
    }
    return mapeo.get(iid, nombre[:24])


def build_threshold_info(iid: str, thresholds: dict, unidad: str) -> dict | None:
    """Traduce thresholds.json para un indicador a un dict legible para el template.
    Devuelve None si no hay calibración (indicador neutro por default).
    """
    t_id = thresholds.get(iid) if thresholds else None
    if not t_id:
        return None
    campo_key = next(iter(t_id))
    t = t_id[campo_key]
    tipo = t.get("tipo")
    u = unidad or ""
    if tipo == "max":
        vmax = t.get("verde_max")
        amax = t.get("amarillo_max")
        rangos = [
            ("verde", f"menor a {vmax}{u}"),
            ("amarillo", f"entre {vmax}{u} y {amax}{u}"),
            ("rojo", f"mayor o igual a {amax}{u}"),
        ]
    elif tipo == "min":
        vmin = t.get("verde_min")
        amin = t.get("amarillo_min")
        rangos = [
            ("verde", f"mayor o igual a {vmin}{u}"),
            ("amarillo", f"entre {amin}{u} y {vmin}{u}"),
            ("rojo", f"menor a {amin}{u}"),
        ]
    else:
        return None
    return {
        "campo": campo_key,
        "tipo": tipo,
        "rangos": rangos,
        "mensaje_amarillo": t.get("mensaje_amarillo"),
        "mensaje_rojo": t.get("mensaje_rojo"),
    }


def build_indicador_ctx(d: dict, iid: str = "", thresholds: dict | None = None) -> dict:
    tabular = d.get("tabular", False)
    unidad = d.get("unidad", "")
    if tabular:
        ultimo = d.get("ultimo")
        stat_valor = fmt_num(ultimo, unidad) if ultimo is not None else "Vista tabular"
        top_concepto = d.get("_top_concepto")
        if top_concepto:
            stat_valor_nota = f"{top_concepto} · {d.get('_label_tabla', '')}"
        else:
            stat_valor_nota = d.get("_label_tabla", "")
        delta = d.get("delta")
        stat_delta = fmt_num(delta, "pp", signed=True) if delta is not None else "—"
        stat_delta_nota = "vs periodo previo" if delta is not None else "Sin comparación directa"
        stat_delta_label = "Δ vs previo"
    else:
        ultimo = d.get("ultimo")
        ma12 = d.get("ma12_ult")
        stat_valor = fmt_num(ultimo, unidad) if ultimo is not None else "—"
        periodos = d.get("periodos") or []
        ultimo_per = periodos[-1] if periodos else "—"
        stat_valor_nota = f"{d.get('campoDefaultLabel') or d.get('campoDefault', '')} · {ultimo_per}"
        if ultimo is not None and ma12 is not None:
            stat_delta = fmt_num(ultimo - ma12, "pp", signed=True)
            stat_delta_nota = f"MA12: {ma12:.1f}{unidad}"
        else:
            stat_delta = "—"
            stat_delta_nota = "Sin histórico suficiente"
        stat_delta_label = "Δ vs MA12"

    interp = d.get("interp") or {"tipo": "pendiente", "mensaje": "Interpretación pendiente."}
    if interp.get("tipo") == "pendiente":
        prox_fecha = (d.get("proximaPub") or {}).get("fecha")
        if prox_fecha and prox_fecha != "—":
            interp = dict(interp)
            interp["mensaje"] = f"Interpretación se generará tras el próximo boletín INEGI del {prox_fecha}."
    _tipo = interp.get("tipo")
    if _tipo == "auto_v2":
        writer = interp.get("writer_provider") or interp.get("provider") or "?"
        verifier = (interp.get("verificacion") or {}).get("verifier_provider")
        if verifier and verifier != writer:
            source = f"{writer} + {verifier}"
        else:
            source = writer
    elif _tipo in ("sonnet", "demo"):
        source = "Claude Sonnet 4.6"
    elif _tipo == "auto":
        source = "DeepSeek"
    else:
        source = "Pendiente"

    threshold_info = build_threshold_info(iid, thresholds or {}, unidad) if iid and thresholds else None

    # Enriquecimiento por indicador (balanza_comercial e inpc_mensual con drilldown)
    drilldown = build_drilldown(iid)

    inegi_strip = build_inegi_strip(d, iid) if iid else None

    ctx = dict(d)
    ctx.update({
        "alerta_label": ALERTA_LABEL.get(d.get("alerta", "neutro"), "—"),
        "stat_valor": stat_valor,
        "stat_valor_nota": stat_valor_nota,
        "stat_delta": stat_delta,
        "stat_delta_nota": stat_delta_nota,
        "stat_delta_label": stat_delta_label,
        "interp": interp,
        "interp_source": source,
        "serie_cols": list((d.get("series") or {}).keys()) if not tabular else [],
        "threshold_info": threshold_info,
        "drilldown": drilldown,
        "inegi_strip": inegi_strip,
    })
    return ctx


def build_drilldown(iid: str) -> dict | None:
    """Carga el archivo data/{iid}.json crudo y arma paneles especializados.

    Solo aplica a indicadores con desagregaciones profundas que ameritan vistas
    específicas en la página detalle. Devuelve None si no aplica.
    """
    from pathlib import Path
    data_path = Path(__file__).resolve().parent.parent / "data" / f"{iid}.json"
    if not data_path.exists():
        return None
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    series_rows = raw.get("series") or []
    periodos = raw.get("periodos") or []
    if not series_rows or not isinstance(series_rows, list) or not isinstance(series_rows[0], dict):
        return None
    # pivote a column-oriented
    cols = {}
    for r in series_rows:
        for k, v in r.items():
            if k == "Periodo" or k == "Mes":
                continue
            cols.setdefault(k, []).append(v)

    if iid == "balanza_comercial":
        return _drilldown_balanza(periodos, cols)
    if iid == "inpc_mensual":
        return _drilldown_inpc(periodos, cols)
    if iid == "inpc_quincenal":
        return _drilldown_inpc_quincenal(periodos, cols)
    if iid == "pib_trimestral":
        return _drilldown_pib(periodos, cols)
    if iid == "igae":
        return _drilldown_igae(periodos, cols)
    if iid == "actividad_industrial":
        return _drilldown_actind(periodos, cols)
    if iid == "consumo_privado":
        return _drilldown_consumo(periodos, cols)
    if iid == "confianza_consumidor":
        return _drilldown_icc(periodos, cols)
    if iid == "emoe_ipm":
        return _drilldown_emoe_ipm(periodos, cols)
    if iid == "emoe_ice":
        return _drilldown_emoe_ice(periodos, cols)
    if iid == "emoe_iat":
        return _drilldown_emoe_iat(periodos, cols)
    if iid == "fbcf":
        return _drilldown_fbcf(periodos, cols)
    if iid == "enoe_mensual":
        return _drilldown_enoe(periodos, cols)
    if iid == "enec":
        return _drilldown_enec(periodos, cols)
    if iid == "comercio_mayoreo":
        return _drilldown_mayoreo(periodos, cols)
    if iid == "comercio_menudeo":
        return _drilldown_menudeo(periodos, cols)
    if iid == "servicios":
        return _drilldown_servicios(periodos, cols)
    if iid == "pib_anual":
        return _drilldown_pib_anual()
    if iid in ("autos_ligeros", "autos_pesados"):
        return _drilldown_autos(iid, periodos, cols)
    if iid == "ind_ciclicos":
        return _drilldown_ind_ciclicos(periodos, cols)
    if iid == "emim":
        return _drilldown_emim(periodos, cols)
    return None


def _drilldown_ind_ciclicos(periodos: list, cols: dict) -> dict:
    """Dos stat cards: Coincidente y Adelantado con sus periodos de referencia distintos."""
    coinc = cols.get("Coincidente", [])
    adel = cols.get("Adelantado", [])

    def _last(series, periodos):
        for i in range(len(series) - 1, -1, -1):
            if series[i] is not None:
                v = round(series[i], 2) if series[i] is not None else None
                if v == -0.0:
                    v = 0.0
                return {"valor": v, "periodo": periodos[i] if i < len(periodos) else ""}
        return {"valor": None, "periodo": ""}

    ult_coinc = _last(coinc, periodos)
    ult_adel = _last(adel, periodos)

    return {
        "tipo": "ind_ciclicos",
        "coincidente": ult_coinc,
        "adelantado": ult_adel,
    }


def _drilldown_pib_anual() -> dict | None:
    """Lee pib_trimestral.json y extrae snapshot de actividades para la página pib_anual."""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    pib_path = data_dir / "pib_trimestral.json"
    if not pib_path.exists():
        return None
    raw = json.loads(pib_path.read_text(encoding="utf-8"))
    series_rows = raw.get("series") or []
    periodos = raw.get("periodos") or []
    if not series_rows:
        return None
    # Última fila con actividades completas
    actividades_keys = ["Primarias_Anual", "Secundarias_Anual", "Terciarias_Anual"]
    ultimo_row, ultimo_periodo = None, "—"
    for i in range(len(series_rows) - 1, -1, -1):
        r = series_rows[i]
        if all(r.get(k) is not None for k in actividades_keys):
            ultimo_row = r
            ultimo_periodo = periodos[i] if i < len(periodos) else "—"
            break
    if not ultimo_row:
        return None
    filas = [
        {"actividad": "PIB total",              "indent": False, "var_trimestral": ultimo_row.get("Trimestral"),            "var_anual": ultimo_row.get("Anual")},
        {"actividad": "Actividades primarias",  "indent": False, "var_trimestral": ultimo_row.get("Primarias_Trimestral"),  "var_anual": ultimo_row.get("Primarias_Anual")},
        {"actividad": "Actividades secundarias","indent": False, "var_trimestral": ultimo_row.get("Secundarias_Trimestral"),"var_anual": ultimo_row.get("Secundarias_Anual")},
        {"actividad": "  Minería",              "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Mineria_Anual")},
        {"actividad": "  Energía, agua, gas",   "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Energia_agua_gas_Anual")},
        {"actividad": "  Construcción",         "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Construccion_Anual")},
        {"actividad": "  Manufacturas",         "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Manufacturas_Anual")},
        {"actividad": "Actividades terciarias", "indent": False, "var_trimestral": ultimo_row.get("Terciarias_Trimestral"), "var_anual": ultimo_row.get("Terciarias_Anual")},
        {"actividad": "  Comercio mayoreo",     "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Comercio_mayoreo_Anual")},
        {"actividad": "  Comercio menudeo",     "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Comercio_menudeo_Anual")},
        {"actividad": "  Transportes",          "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Transportes_Anual")},
        {"actividad": "  Serv. financieros",    "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Servicios_financieros_Anual")},
        {"actividad": "  Serv. profesionales",  "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Servicios_profesionales_Anual")},
        {"actividad": "  Act. gubernamentales", "indent": True,  "var_trimestral": None, "var_anual": ultimo_row.get("Actividades_gubernamentales_Anual")},
    ]
    filas = [f for f in filas if f["var_anual"] is not None or f["var_trimestral"] is not None]
    return {"tipo": "pib_anual", "periodo": ultimo_periodo, "filas": filas}


def _drilldown_autos(iid: str, periodos: list, cols: dict) -> dict:
    """Panel multi-series de variación anual para autos ligeros y pesados."""
    p_recent, c = _slice_recent(periodos, cols, 24)
    if iid == "autos_ligeros":
        variables = ["Ventas", "Producción", "Exportación"]
    else:
        variables = ["Ventas_Menudeo", "Ventas_Mayoreo", "Producción", "Exportación"]
    series = {v: c.get(v) for v in variables if v in c}
    ultimo = {v: _ult_no_none(cols.get(v)) for v in variables}
    return {
        "tipo": iid,
        "periodos": p_recent,
        "series": series,
        "ultimo": ultimo,
    }


def _drilldown_emim(periodos: list, cols: dict) -> dict:
    """4 stat cards con la última variación mensual desest. de cada variable EMIM."""
    variables = [
        ("Producción", "Volumen_producción"),
        ("Personal ocupado", "Personal_ocupado"),
        ("Horas trabajadas", "Horas_trabajadas"),
        ("Remuneraciones medias reales", "Remuneraciones_medias_reales"),
    ]
    # Última observación no-null de cada variable (puede diferir entre variables)
    ultimo = {}
    periodo_ref = periodos[-1] if periodos else ""
    for nombre, col in variables:
        val = _ult_no_none(cols.get(col))
        ultimo[nombre] = val
    # Periodo de referencia: el más reciente con Volumen_producción no-null
    coinc_col = cols.get("Volumen_producción", [])
    for i in range(len(coinc_col) - 1, -1, -1):
        if coinc_col[i] is not None:
            periodo_ref = periodos[i] if i < len(periodos) else periodo_ref
            break
    return {
        "tipo": "emim",
        "periodo": periodo_ref,
        "ultimo": ultimo,
    }


def _drilldown_enec(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    obras = [
        ("Edificación", "Edificacion_Anual"),
        ("Agua y saneamiento", "Agua_saneamiento_Anual"),
        ("Electricidad y telecom", "Electricidad_telecom_Anual"),
        ("Transporte y urbanización", "Transporte_urbanizacion_Anual"),
        ("Petróleo y petroquímica", "Petroleo_petroquimica_Anual"),
        ("Otras construcciones", "Otras_construcciones_Anual"),
    ]
    return {
        "tipo": "enec",
        "periodos": p_recent,
        "obras": {nombre: c.get(col) for nombre, col in obras},
        "ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in obras},
    }


def _drilldown_mayoreo(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    return {
        "tipo": "comercio_mayoreo",
        "periodos": p_recent,
        "ramas": {
            "Productos farma/perf": c.get("Productos_farma_perf_Anual"),
            "Intermediación": c.get("Intermediacion_Anual"),
        },
        "ultimo": {
            "Productos farma/perf": _ult_no_none(cols.get("Productos_farma_perf_Anual")),
            "Intermediación": _ult_no_none(cols.get("Intermediacion_Anual")),
        },
    }


def _drilldown_menudeo(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    sectores = [
        ("Vehículos y combustibles", "Vehiculos_combustibles_Anual"),
        ("Textiles y calzado", "Textiles_calzado_Anual"),
        ("Papelería y esparcimiento", "Papeleria_esparcimiento_Anual"),
        ("Ferretería", "Ferreteria_Anual"),
        ("Internet y catálogos", "Internet_catalogos_Anual"),
    ]
    return {
        "tipo": "comercio_menudeo",
        "periodos": p_recent,
        "sectores": {nombre: c.get(col) for nombre, col in sectores},
        "ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in sectores},
    }


def _drilldown_servicios(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    sectores = [
        ("Transporte y correos", "Transporte_correos_Anual"),
        ("Info medios masivos", "Info_medios_masivos_Anual"),
        ("Inmobiliarios y alquiler", "Inmobiliarios_alquiler_Anual"),
        ("Profesionales y científicos", "Profesionales_cientificos_Anual"),
        ("Apoyo negocios y residuos", "Apoyo_negocios_residuos_Anual"),
        ("Educativos", "Educativos_Anual"),
        ("Salud y asistencia", "Salud_asistencia_Anual"),
        ("Esparcimiento y culturales", "Esparcimiento_culturales_Anual"),
        ("Alojamiento y alimentos", "Alojamiento_alimentos_Anual"),
        ("Otros servicios", "Otros_servicios_Anual"),
    ]
    return {
        "tipo": "servicios",
        "periodos": p_recent,
        "sectores": {nombre: c.get(col) for nombre, col in sectores},
        "ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in sectores},
    }


def _ult_no_none(lst: list, idx: int = -1):
    """Devuelve el último valor no-None desde idx hacia atrás."""
    if not lst:
        return None
    for v in reversed(lst[: len(lst) + idx + 1] if idx < 0 else lst[: idx + 1]):
        if v is not None:
            return v
    return None


def _drilldown_igae(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    return {
        "tipo": "igae",
        "periodos": p_recent,
        "actividades": {
            "Total": c.get("Total_Anual"),
            "Primarias": c.get("Primarias_Anual"),
            "Secundarias": c.get("Secundarias_Anual"),
            "Terciarias": c.get("Terciarias_Anual"),
        },
        "secundarias": {
            "Minería (21)": c.get("Mineria_Anual"),
            "Energía (22)": c.get("Energia_agua_gas_Anual"),
            "Construcción (23)": c.get("Construccion_Anual"),
            "Manufacturas (31-33)": c.get("Manufacturas_Anual"),
        },
        "terciarias": {
            "Comercio mayoreo (43)": c.get("Comercio_mayoreo_Anual"),
            "Comercio menudeo (46)": c.get("Comercio_menudeo_Anual"),
            "Transportes (48-49)": c.get("Transportes_Anual"),
            "Financieros (52)": c.get("Servicios_financieros_Anual"),
            "Inmobiliarios (53)": c.get("Servicios_inmobiliarios_Anual"),
            "Profesionales (54)": c.get("Servicios_profesionales_Anual"),
            "Gobierno (93)": c.get("Actividades_gubernamentales_Anual"),
        },
        "ultimo": {
            "PIB total": _ult_no_none(cols.get("Total_Anual")),
            "Primarias": _ult_no_none(cols.get("Primarias_Anual")),
            "Secundarias": _ult_no_none(cols.get("Secundarias_Anual")),
            "Terciarias": _ult_no_none(cols.get("Terciarias_Anual")),
        },
        "secundarias_ultimo": {
            nombre: _ult_no_none(cols.get(col))
            for nombre, col in [
                ("Minería", "Mineria_Anual"),
                ("Energía", "Energia_agua_gas_Anual"),
                ("Construcción", "Construccion_Anual"),
                ("Manufacturas", "Manufacturas_Anual"),
            ]
        },
        "terciarias_ultimo": {
            nombre: _ult_no_none(cols.get(col))
            for nombre, col in [
                ("Comercio mayoreo", "Comercio_mayoreo_Anual"),
                ("Comercio menudeo", "Comercio_menudeo_Anual"),
                ("Transportes", "Transportes_Anual"),
                ("Financieros", "Servicios_financieros_Anual"),
                ("Inmobiliarios", "Servicios_inmobiliarios_Anual"),
                ("Profesionales", "Servicios_profesionales_Anual"),
                ("Gobierno", "Actividades_gubernamentales_Anual"),
            ]
        },
    }


def _drilldown_actind(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    subsectores_keys = [
        ("Alimentos", "Alimentos_Anual"),
        ("Bebidas", "Bebidas_Anual"),
        ("Textil", "Textil_Anual"),
        ("Cuero", "Cuero_Anual"),
        ("Madera", "Madera_Anual"),
        ("Papel", "Papel_Anual"),
        ("Química", "Quimica_Anual"),
        ("Plástico", "Plastico_Anual"),
        ("Metales", "Metales_Anual"),
        ("Metálicos", "Metalicos_Anual"),
        ("Maquinaria", "Maquinaria_Anual"),
        ("Computación", "Computacion_Anual"),
        ("Eléctrico", "Electrico_Anual"),
        ("Transporte", "Transporte_Anual"),
    ]
    return {
        "tipo": "actividad_industrial",
        "periodos": p_recent,
        "sectores": {
            "Total": c.get("Total"),
            "Minería": c.get("Minería"),
            "Energía": c.get("Energía_agua_gas"),
            "Construcción": c.get("Construcción"),
            "Manufactureras": c.get("Manufactureras"),
        },
        "subsectores_manuf": {nombre: c.get(col) for nombre, col in subsectores_keys},
        "subsectores_ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in subsectores_keys},
    }


def _drilldown_consumo(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    periodo_ref = periodos[-1] if periodos else ""
    cuadro_filas = [
        ("Consumo privado total", "Total_Mensual", "Total_Anual"),
        ("Nacional", "Origen_nacional_Mensual", "Origen_nacional_Anual"),
        (" Bienes", None, None),
        (" Servicios", None, "Servicios_nacional_Anual"),
        ("Importado", "Origen_importado_Mensual", "Origen_importado_Anual"),
    ]
    cuadro = []
    for label, col_men, col_anu in cuadro_filas:
        cuadro.append({
            "label": label,
            "mensual": _ult_no_none(cols.get(col_men)) if col_men else None,
            "anual": _ult_no_none(cols.get(col_anu)) if col_anu else None,
        })
    return {
        "tipo": "consumo_privado",
        "periodo": periodo_ref,
        "periodos": p_recent,
        "cuadro": cuadro,
        "origen": {
            "Total": c.get("Total_Anual"),
            "Origen nacional": c.get("Origen_nacional_Anual"),
            "Origen importado": c.get("Origen_importado_Anual"),
        },
        "tipo_bien_nacional": {
            "Duraderos": c.get("Duraderos_nacional_Anual"),
            "Semi-duraderos": c.get("Semi_duraderos_nacional_Anual"),
            "No duraderos": c.get("No_duraderos_nacional_Anual"),
            "Servicios": c.get("Servicios_nacional_Anual"),
        },
        "tipo_bien_importado": {
            "Duraderos importados": c.get("Duraderos_importado_Anual"),
            "Semi-duraderos importados": c.get("Semi_duraderos_importado_Anual"),
            "No duraderos importados": c.get("No_duraderos_importado_Anual"),
        },
        "ultimo": {
            "Total": _ult_no_none(cols.get("Total_Anual")),
            "Nacional": _ult_no_none(cols.get("Origen_nacional_Anual")),
            "Importado": _ult_no_none(cols.get("Origen_importado_Anual")),
            "Duraderos nacional": _ult_no_none(cols.get("Duraderos_nacional_Anual")),
            "Semi-duraderos nacional": _ult_no_none(cols.get("Semi_duraderos_nacional_Anual")),
            "No duraderos nacional": _ult_no_none(cols.get("No_duraderos_nacional_Anual")),
            "Servicios nacional": _ult_no_none(cols.get("Servicios_nacional_Anual")),
        },
    }


def _build_radar(component_map: list[tuple[str, str]], cols: dict, periodos: list) -> dict | None:
    """Construye payload para radar chart: último período vs hace 12 meses."""
    if not periodos or len(periodos) < 13:
        return None
    labels = [nombre for nombre, _ in component_map]
    current = [_ult_no_none(cols.get(col)) for _, col in component_map]
    prev = [_ult_no_none(cols.get(col), idx=-13) for _, col in component_map]
    periodo_actual = periodos[-1]
    periodo_prev = periodos[-13] if len(periodos) >= 13 else periodos[0]
    # Omitir si no hay valores
    if all(v is None for v in current):
        return None
    return {
        "labels": labels,
        "current": current,
        "prev": prev,
        "periodo_actual": periodo_actual,
        "periodo_prev": periodo_prev,
    }


def _drilldown_icc(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    radar_map = [
        ("Hogar actual", "Hogar_actual_Anual"),
        ("Hogar futura", "Hogar_futura_Anual"),
        ("País actual", "Pais_actual_Anual"),
        ("País futura", "Pais_futura_Anual"),
        ("Compra durables", "Compra_durables_Anual"),
    ]
    return {
        "tipo": "confianza_consumidor",
        "periodos": p_recent,
        "componentes": {
            "ICC anual": c.get("Anual"),
            "Hogar actual": c.get("Hogar_actual_Anual"),
            "Hogar futura": c.get("Hogar_futura_Anual"),
            "País actual": c.get("Pais_actual_Anual"),
            "País futura": c.get("Pais_futura_Anual"),
            "Compra durables": c.get("Compra_durables_Anual"),
        },
        "ultimo": {
            "ICC anual": _ult_no_none(cols.get("Anual")),
            "Hogar actual": _ult_no_none(cols.get("Hogar_actual_Anual")),
            "Hogar futura": _ult_no_none(cols.get("Hogar_futura_Anual")),
            "País actual": _ult_no_none(cols.get("Pais_actual_Anual")),
            "País futura": _ult_no_none(cols.get("Pais_futura_Anual")),
            "Compra durables": _ult_no_none(cols.get("Compra_durables_Anual")),
        },
        "radar": _build_radar(radar_map, cols, periodos),
    }


def _drilldown_emoe_ipm(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    radar_map = [
        ("Pedidos esperados", "Pedidos_esperados_Anual"),
        ("Producción esperada", "Produccion_esperada_Anual"),
        ("Personal ocupado", "Personal_ocupado_Anual"),
        ("Entrega insumos", "Entrega_insumos_Anual"),
        ("Inventarios", "Inventarios_Anual"),
    ]
    return {
        "tipo": "emoe_ipm",
        "periodos": p_recent,
        "componentes": {
            "IPM total": c.get("Anual"),
            "Pedidos esperados": c.get("Pedidos_esperados_Anual"),
            "Producción esperada": c.get("Produccion_esperada_Anual"),
            "Personal ocupado": c.get("Personal_ocupado_Anual"),
            "Entrega de insumos": c.get("Entrega_insumos_Anual"),
            "Inventarios": c.get("Inventarios_Anual"),
        },
        "ultimo": {nombre: _ult_no_none(c.get(col)) for nombre, col in [
            ("IPM total", "Anual"),
            ("Pedidos", "Pedidos_esperados_Anual"),
            ("Producción", "Produccion_esperada_Anual"),
            ("Personal", "Personal_ocupado_Anual"),
            ("Entrega insumos", "Entrega_insumos_Anual"),
            ("Inventarios", "Inventarios_Anual"),
        ]},
        "radar": _build_radar(radar_map, cols, periodos),
    }


def _drilldown_emoe_ice(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    radar_map = [
        ("Manufacturas", "ICE_manufacturas_Anual"),
        ("Construcción", "ICE_construccion_Anual"),
        ("Comercio", "ICE_comercio_Anual"),
        ("Servicios", "ICE_servicios_Anual"),
    ]
    return {
        "tipo": "emoe_ice",
        "periodos": p_recent,
        "sectores": {
            "ICE global": c.get("Anual"),
            "Manufacturas": c.get("ICE_manufacturas_Anual"),
            "Construcción": c.get("ICE_construccion_Anual"),
            "Comercio": c.get("ICE_comercio_Anual"),
            "Servicios": c.get("ICE_servicios_Anual"),
        },
        "ultimo": {nombre: _ult_no_none(c.get(col)) for nombre, col in [
            ("ICE global", "Anual"),
            ("Manufacturas", "ICE_manufacturas_Anual"),
            ("Construcción", "ICE_construccion_Anual"),
            ("Comercio", "ICE_comercio_Anual"),
            ("Servicios", "ICE_servicios_Anual"),
        ]},
        "radar": _build_radar(radar_map, cols, periodos),
    }


def _drilldown_emoe_iat(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    return {
        "tipo": "emoe_iat",
        "periodos": p_recent,
        "sectores": {
            "IAT global": c.get("Anual"),
            "Construcción": c.get("IAT_construccion_Anual"),
            "Comercio": c.get("IAT_comercio_Anual"),
        },
        "ultimo": {nombre: _ult_no_none(c.get(col)) for nombre, col in [
            ("IAT global", "Anual"),
            ("Construcción", "IAT_construccion_Anual"),
            ("Comercio", "IAT_comercio_Anual"),
        ]},
    }


def _drilldown_fbcf(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    periodo_ref = periodos[-1] if periodos else ""
    cuadro_filas = [
        ("Formación bruta de capital fijo", "Total_Mensual", "Total_Anual"),
        ("Construcción", "Construcción_Mensual", "Construcción_Anual"),
        (" Residencial", None, "Construccion_residencial_Anual"),
        (" No residencial", None, "Construccion_no_residencial_Anual"),
        ("Maquinaria y equipo", "Maquinaria_y_equipo_Mensual", "Maquinaria_y_equipo_Anual"),
        (" Nacional", None, "Maquinaria_nacional_Anual"),
        (" Importada", None, "Maquinaria_importada_Anual"),
    ]
    cuadro = []
    for label, col_men, col_anu in cuadro_filas:
        cuadro.append({
            "label": label,
            "mensual": _ult_no_none(cols.get(col_men)) if col_men else None,
            "anual": _ult_no_none(cols.get(col_anu)) if col_anu else None,
        })
    return {
        "tipo": "fbcf",
        "periodo": periodo_ref,
        "periodos": p_recent,
        "cuadro": cuadro,
        "totales": {
            "FBCF total": c.get("Total_Anual"),
            "Maquinaria y equipo": c.get("Maquinaria_y_equipo_Anual"),
            "Construcción": c.get("Construcción_Anual"),
        },
        "construccion_partida": {
            "Residencial": c.get("Construccion_residencial_Anual"),
            "No residencial": c.get("Construccion_no_residencial_Anual"),
        },
        "maquinaria_partida": {
            "Nacional": c.get("Maquinaria_nacional_Anual"),
            "Importada": c.get("Maquinaria_importada_Anual"),
        },
        "ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in [
            ("FBCF total", "Total_Anual"),
            ("Maquinaria y equipo", "Maquinaria_y_equipo_Anual"),
            ("Construcción", "Construcción_Anual"),
            ("Construcción residencial", "Construccion_residencial_Anual"),
            ("Construcción no residencial", "Construccion_no_residencial_Anual"),
            ("Maquinaria nacional", "Maquinaria_nacional_Anual"),
            ("Maquinaria importada", "Maquinaria_importada_Anual"),
        ]},
    }


def _drilldown_enoe(periodos: list, cols: dict) -> dict:
    p_recent, c = _slice_recent(periodos, cols, 60)
    return {
        "tipo": "enoe_mensual",
        "periodos": p_recent,
        "desocupacion": {
            "Total": c.get("Tasa_desocupacion_Total"),
            "Hombres": c.get("Tasa_desocupacion_Hombres"),
            "Mujeres": c.get("Tasa_desocupacion_Mujeres"),
            "Urbana": c.get("Tasa_desocupacion_urbana"),
        },
        "participacion": {
            "Total": c.get("Tasa_participacion_Total"),
            "Hombres": c.get("Tasa_participacion_Hombres"),
            "Mujeres": c.get("Tasa_participacion_Mujeres"),
            "Urbana": c.get("Tasa_participacion_urbana"),
        },
        "informalidad_subocupacion": {
            "Informalidad nacional": c.get("Tasa_informalidad"),
            "Informalidad urbana": c.get("Tasa_informalidad_urbana"),
            "Subocupación nacional": c.get("Tasa_subocupacion"),
            "Subocupación urbana": c.get("Tasa_subocupacion_urbana"),
        },
        "ultimo": {nombre: _ult_no_none(cols.get(col)) for nombre, col in [
            ("Desoc. Total", "Tasa_desocupacion_Total"),
            ("Desoc. Hombres", "Tasa_desocupacion_Hombres"),
            ("Desoc. Mujeres", "Tasa_desocupacion_Mujeres"),
            ("Desoc. Urbana", "Tasa_desocupacion_urbana"),
            ("Partic. Total", "Tasa_participacion_Total"),
            ("Informalidad", "Tasa_informalidad"),
            ("Subocupación", "Tasa_subocupacion"),
        ]},
    }


def _slice_recent(periodos: list, cols: dict, n: int = 60) -> tuple[list, dict]:
    """Devuelve los últimos n meses de periodos y cada columna."""
    p = periodos[-n:]
    c = {k: v[-n:] for k, v in cols.items()}
    return p, c


def _drilldown_balanza(periodos: list, cols: dict) -> dict:
    """Paneles para balanza_comercial: saldos MDD, composición exp/imp."""
    p_recent, cols_recent = _slice_recent(periodos, cols, 60)
    ult_idx = -1
    return {
        "tipo": "balanza_comercial",
        "periodos": p_recent,
        "saldos": {
            "Total": cols_recent.get("Saldo_total_MDD"),
            "Petrolero": cols_recent.get("Saldo_petrolero_MDD"),
            "No petrolero": cols_recent.get("Saldo_no_petrolero_MDD"),
        },
        "saldos_ultimo": {
            "Total": (cols.get("Saldo_total_MDD") or [None])[ult_idx],
            "Petrolero": (cols.get("Saldo_petrolero_MDD") or [None])[ult_idx],
            "No petrolero": (cols.get("Saldo_no_petrolero_MDD") or [None])[ult_idx],
        },
        "export_composicion": {
            "Petroleras": cols_recent.get("Export_petroleras_Anual"),
            "No petroleras": cols_recent.get("Export_no_petroleras_Anual"),
            "Agropecuarias": cols_recent.get("Export_agropecuarias_Anual"),
            "Extractivas": cols_recent.get("Export_extractivas_Anual"),
            "Manufacturas total": cols_recent.get("Export_manufacturas_Anual"),
            "Automotriz": cols_recent.get("Export_automotriz_Anual"),
            "Resto manufacturas": cols_recent.get("Export_resto_manuf_Anual"),
        },
        "export_ultimo": {
            "Petroleras": (cols.get("Export_petroleras_Anual") or [None])[ult_idx],
            "No petroleras": (cols.get("Export_no_petroleras_Anual") or [None])[ult_idx],
            "Agropecuarias": (cols.get("Export_agropecuarias_Anual") or [None])[ult_idx],
            "Extractivas": (cols.get("Export_extractivas_Anual") or [None])[ult_idx],
            "Manufacturas total": (cols.get("Export_manufacturas_Anual") or [None])[ult_idx],
            "Automotriz": (cols.get("Export_automotriz_Anual") or [None])[ult_idx],
            "Resto manufacturas": (cols.get("Export_resto_manuf_Anual") or [None])[ult_idx],
        },
        "import_tipo": {
            "Consumo": cols_recent.get("Import_consumo_Anual"),
            "Intermedios": cols_recent.get("Import_intermedios_Anual"),
            "Capital": cols_recent.get("Import_capital_Anual"),
        },
        "import_ultimo": {
            "Consumo": (cols.get("Import_consumo_Anual") or [None])[ult_idx],
            "Intermedios": (cols.get("Import_intermedios_Anual") or [None])[ult_idx],
            "Capital": (cols.get("Import_capital_Anual") or [None])[ult_idx],
        },
    }


def _drilldown_pib(periodos: list, cols: dict) -> dict:
    """Paneles para pib_trimestral: 3 grandes actividades, subsectores, demanda agregada."""
    p_recent, cols_recent = _slice_recent(periodos, cols, 40)
    ult_idx = -1
    return {
        "tipo": "pib_trimestral",
        "periodos": p_recent,
        "actividades_anual": {
            "Total": cols_recent.get("Anual"),
            "Primarias": cols_recent.get("Primarias_Anual"),
            "Secundarias": cols_recent.get("Secundarias_Anual"),
            "Terciarias": cols_recent.get("Terciarias_Anual"),
        },
        "actividades_ultimo": {
            "PIB total": (cols.get("Anual") or [None])[ult_idx],
            "Primarias": (cols.get("Primarias_Anual") or [None])[ult_idx],
            "Secundarias": (cols.get("Secundarias_Anual") or [None])[ult_idx],
            "Terciarias": (cols.get("Terciarias_Anual") or [None])[ult_idx],
        },
        "secundarias_anual": {
            "Minería (21)": cols_recent.get("Mineria_Anual"),
            "Energía/agua/gas (22)": cols_recent.get("Energia_agua_gas_Anual"),
            "Construcción (23)": cols_recent.get("Construccion_Anual"),
            "Manufacturas (31-33)": cols_recent.get("Manufacturas_Anual"),
        },
        "secundarias_ultimo": {
            "Minería": (cols.get("Mineria_Anual") or [None])[ult_idx-1] if (cols.get("Mineria_Anual") or [None])[ult_idx] is None else (cols.get("Mineria_Anual") or [None])[ult_idx],
            "Energía/agua/gas": (cols.get("Energia_agua_gas_Anual") or [None])[ult_idx-1] if (cols.get("Energia_agua_gas_Anual") or [None])[ult_idx] is None else (cols.get("Energia_agua_gas_Anual") or [None])[ult_idx],
            "Construcción": (cols.get("Construccion_Anual") or [None])[ult_idx-1] if (cols.get("Construccion_Anual") or [None])[ult_idx] is None else (cols.get("Construccion_Anual") or [None])[ult_idx],
            "Manufacturas": (cols.get("Manufacturas_Anual") or [None])[ult_idx-1] if (cols.get("Manufacturas_Anual") or [None])[ult_idx] is None else (cols.get("Manufacturas_Anual") or [None])[ult_idx],
        },
        "terciarias_anual": {
            "Comercio mayoreo (43)": cols_recent.get("Comercio_mayoreo_Anual"),
            "Comercio menudeo (46)": cols_recent.get("Comercio_menudeo_Anual"),
            "Transportes (48-49)": cols_recent.get("Transportes_Anual"),
            "Servicios financieros (52)": cols_recent.get("Servicios_financieros_Anual"),
            "Servicios inmobiliarios (53)": cols_recent.get("Servicios_inmobiliarios_Anual"),
            "Servicios profesionales (54)": cols_recent.get("Servicios_profesionales_Anual"),
            "Actividades gubernamentales (93)": cols_recent.get("Actividades_gubernamentales_Anual"),
        },
        "terciarias_ultimo": {
            nombre: (cols.get(col) or [None])[ult_idx-1] if (cols.get(col) or [None])[ult_idx] is None else (cols.get(col) or [None])[ult_idx]
            for nombre, col in [
                ("Comercio mayoreo", "Comercio_mayoreo_Anual"),
                ("Comercio menudeo", "Comercio_menudeo_Anual"),
                ("Transportes", "Transportes_Anual"),
                ("Servicios financieros", "Servicios_financieros_Anual"),
                ("Servicios inmobiliarios", "Servicios_inmobiliarios_Anual"),
                ("Servicios profesionales", "Servicios_profesionales_Anual"),
                ("Actividades gubernamentales", "Actividades_gubernamentales_Anual"),
            ]
        },
        "demanda_anual": {
            "Consumo privado": cols_recent.get("Demanda_consumo_privado_Anual"),
            "Consumo gobierno": cols_recent.get("Demanda_consumo_gobierno_Anual"),
            "FBCF total": cols_recent.get("Demanda_FBCF_total_Anual"),
            "Exportaciones bienes y servicios": cols_recent.get("Demanda_export_byserv_Anual"),
            "Importaciones bienes y servicios": cols_recent.get("Demanda_import_byserv_Anual"),
        },
        "demanda_ultimo": {
            "Consumo privado": (cols.get("Demanda_consumo_privado_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_consumo_privado_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_consumo_privado_Anual") or [None])[ult_idx],
            "Consumo gobierno": (cols.get("Demanda_consumo_gobierno_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_consumo_gobierno_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_consumo_gobierno_Anual") or [None])[ult_idx],
            "FBCF total": (cols.get("Demanda_FBCF_total_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_FBCF_total_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_FBCF_total_Anual") or [None])[ult_idx],
            "FBCF privada": (cols.get("Demanda_FBCF_privada_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_FBCF_privada_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_FBCF_privada_Anual") or [None])[ult_idx],
            "FBCF pública": (cols.get("Demanda_FBCF_publica_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_FBCF_publica_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_FBCF_publica_Anual") or [None])[ult_idx],
            "Exportaciones B+S": (cols.get("Demanda_export_byserv_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_export_byserv_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_export_byserv_Anual") or [None])[ult_idx],
            "Importaciones B+S": (cols.get("Demanda_import_byserv_Anual") or [None])[ult_idx-1] if (cols.get("Demanda_import_byserv_Anual") or [None])[ult_idx] is None else (cols.get("Demanda_import_byserv_Anual") or [None])[ult_idx],
        },
    }


def _build_heatmap_mensual(periodos: list, inpc_anual_vals: list, year_from: int = 2000) -> dict | None:
    """Construye heatmap año×mes para INPC mensual.
    Devuelve {years, months, grid: {year_str: {mes_abbr: value}}} filtrado desde year_from.
    """
    meses_abbr = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    grid: dict[str, dict[str, float | None]] = {}
    for p, v in zip(periodos, inpc_anual_vals):
        # Formato: "ene-69", "mar-26"
        try:
            mes_abbr, yr2 = p.split("-")
            yr = int(yr2)
            year = 2000 + yr if yr <= 30 else 1900 + yr
            if year < year_from:
                continue
            yr_key = str(year)
            grid.setdefault(yr_key, {})[mes_abbr] = v
        except Exception:
            continue
    if not grid:
        return None
    years = sorted(grid.keys())
    return {"years": years, "months": meses_abbr, "grid": grid}


def _drilldown_inpc(periodos: list, cols: dict) -> dict:
    """Paneles para inpc_mensual: subyacente, no subyacente y heatmap."""
    p_recent, cols_recent = _slice_recent(periodos, cols, 60)
    ult_idx = -1
    inpc_anual_all = cols.get("INPC_Anual") or []
    heatmap = _build_heatmap_mensual(periodos, inpc_anual_all, year_from=2000)
    return {
        "tipo": "inpc_mensual",
        "periodos": p_recent,
        "subyacente_partido_anual": {
            "Mercancías": cols_recent.get("Subyacente_mercancias_Anual"),
            "Servicios": cols_recent.get("Subyacente_servicios_Anual"),
            "Subyacente total": cols_recent.get("Subyacente_Anual"),
        },
        "no_subyacente_partido_anual": {
            "Agropecuarios": cols_recent.get("No_subyacente_agropecuarios_Anual"),
            "Energéticos y tarifas": cols_recent.get("No_subyacente_energeticos_Anual"),
            "No subyacente total": cols_recent.get("No_subyacente_Anual"),
        },
        "general_vs_subyacente_anual": {
            "INPC general": cols_recent.get("INPC_Anual"),
            "Subyacente": cols_recent.get("Subyacente_Anual"),
            "No subyacente": cols_recent.get("No_subyacente_Anual"),
        },
        "ultimo": {
            "INPC general": (cols.get("INPC_Anual") or [None])[ult_idx],
            "Subyacente total": (cols.get("Subyacente_Anual") or [None])[ult_idx],
            "Subyacente mercancías": (cols.get("Subyacente_mercancias_Anual") or [None])[ult_idx],
            "Subyacente servicios": (cols.get("Subyacente_servicios_Anual") or [None])[ult_idx],
            "No subyacente total": (cols.get("No_subyacente_Anual") or [None])[ult_idx],
            "No subyacente agropecuarios": (cols.get("No_subyacente_agropecuarios_Anual") or [None])[ult_idx],
            "No subyacente energéticos": (cols.get("No_subyacente_energeticos_Anual") or [None])[ult_idx],
        },
        "heatmap": heatmap,
    }


def _drilldown_inpc_quincenal(periodos: list, cols: dict) -> dict:
    """Heatmap año×quincena para inpc_quincenal."""
    inpc_anual_all = cols.get("INPC_Anual") or []
    # Periodos formato "Q01-88", Q01-Q24 por año
    grid: dict[str, dict[str, float | None]] = {}
    for p, v in zip(periodos, inpc_anual_all):
        try:
            qpart, yr2 = p.split("-")  # "Q01", "88"
            yr = int(yr2)
            year = 2000 + yr if yr <= 30 else 1900 + yr
            if year < 2000:
                continue
            yr_key = str(year)
            grid.setdefault(yr_key, {})[qpart] = v
        except Exception:
            continue
    if not grid:
        return None
    years = sorted(grid.keys())
    # Columnas: Q01..Q24
    all_qs = sorted({q for yr_data in grid.values() for q in yr_data.keys()})
    return {
        "tipo": "inpc_quincenal",
        "heatmap": {"years": years, "months": all_qs, "grid": grid},
    }


# ------------- reporte semanal -------------

def _sparkline_svg(series: list, alerta: str, width: int = 120, height: int = 34) -> str:
    """Genera un SVG inline de sparkline a partir de una lista de valores numéricos."""
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < 3:
        return ""
    # Últimos 24 puntos
    vals = vals[-24:]
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    pad_x, pad_y = 2, 3
    uw = (width - pad_x * 2) / max(len(vals) - 1, 1)
    color_map = {"rojo": "#DC2626", "amarillo": "#D97706", "verde": "#16A34A", "neutro": "#71717A"}
    stroke = color_map.get(alerta, "#71717A")
    pts = []
    for i, v in enumerate(vals):
        x = pad_x + i * uw
        y = height - pad_y - ((v - mn) / rng) * (height - pad_y * 2)
        pts.append(f"{x:.1f},{y:.1f}")
    polyline = " ".join(pts)
    # Área rellena bajo la línea
    first_x, last_x = pad_x, pad_x + (len(vals) - 1) * uw
    area_pts = f"{first_x:.1f},{height - pad_y} " + polyline + f" {last_x:.1f},{height - pad_y}"
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'aria-hidden="true" style="display:block;width:{width}px;height:{height}px">'
        f'<polygon points="{area_pts}" fill="{stroke}" opacity="0.12"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{stroke}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def build_reporte_semanal(
    env: Environment,
    indicadores: dict,
    calendar: dict,
    thresholds: dict,
    hoy: date,
) -> None:
    """Genera site/reporte_semanal.html con los indicadores publicados en los últimos 14 días."""
    from datetime import timedelta
    from normalize import serie_label as _slabel

    # Indicadores estratégicos (jerarquía macro prioritaria)
    PRIORITY_IDS = {
        "inpc_mensual", "inflacion_resumen", "igae", "igae_ioae_resumen",
        "enoe_trimestral", "empleo_imss", "balanza_comercial", "pib_trimestral",
    }

    # Mapa de tema por indicador para síntesis ejecutiva agrupada
    TEMA_MAP = {
        "igae": "Actividad", "igae_ioae_resumen": "Actividad",
        "actividad_industrial": "Actividad", "consumo_privado": "Actividad",
        "fbcf": "Actividad", "servicios": "Actividad", "ind_ciclicos": "Actividad",
        "pib_trimestral": "Actividad", "pib_anual": "Actividad", "pib_por_actividad": "Actividad",
        "emim": "Manufactura", "enec": "Construcción",
        "comercio_mayoreo": "Consumo", "comercio_menudeo": "Consumo",
        "balanza_comercial": "Sector externo", "export_entidad": "Sector externo",
        "inpc_mensual": "Inflación", "inpc_quincenal": "Inflación",
        "inpp": "Inflación", "inflacion_resumen": "Inflación",
        "enoe_trimestral": "Empleo", "enoe_mensual": "Empleo", "empleo_imss": "Empleo",
        "confianza_consumidor": "Sentimiento", "emoe_ipm": "Sentimiento",
        "emoe_iat": "Sentimiento", "emoe_ice": "Sentimiento",
        "itaee_estatal": "Regional", "imai_estatal": "Regional",
    }

    # Cargar frecuencia por indicador desde el catálogo
    catalog_path = ROOT / "config" / "indicators.json"
    frecuencia_map: dict[str, str] = {}
    if catalog_path.exists():
        for meta in json.loads(catalog_path.read_text(encoding="utf-8")).get("indicadores", []):
            frecuencia_map[meta["id"]] = meta.get("frecuencia") or ""

    ventana = 14
    hoy_iso = hoy.isoformat()

    # --- Indicadores publicados ---
    publicados: list[dict] = []
    for iid, cal in calendar.items():
        ultima = cal.get("ultima_publicacion_ics") or {}
        fecha_pub = ultima.get("fecha")
        if not fecha_pub:
            continue
        try:
            dias = (hoy - date.fromisoformat(fecha_pub)).days
        except ValueError:
            continue
        if dias < 0 or dias > ventana:
            continue

        d = indicadores.get(iid)
        if not d:
            continue

        ctx = build_indicador_ctx(d, iid=iid, thresholds=thresholds)
        tabular = d.get("tabular", False)
        ultimo_val = d.get("ultimo")
        delta = d.get("delta")
        unidad = d.get("unidad", "")
        periodos = d.get("periodos") or []

        if not tabular and ultimo_val is not None:
            stat_valor_num = f"{ultimo_val:.1f}"
            unidad_corta = unidad
        else:
            stat_valor_num = "—"
            unidad_corta = ""

        if delta is not None:
            stat_delta = f"{'+' if delta > 0 else ''}{delta:.1f}pp"
            delta_sign = "+" if delta > 0 else ("-" if delta < 0 else "0")
        else:
            stat_delta = "—"
            delta_sign = "0"

        periodo_ref = periodos[-1] if periodos else ""

        try:
            pub_dt = date.fromisoformat(fecha_pub)
            fecha_pub_display = f"{pub_dt.day} {MESES[pub_dt.month - 1]} {pub_dt.year}"
        except Exception:
            fecha_pub_display = fecha_pub

        # Contexto: prefiere headline ejecutivo del writer+verifier (auto_v2);
        # fallback al mensaje legacy o a una construcción simple basada en MA12.
        interp = d.get("interp") or {}
        tipo_interp = interp.get("tipo", "pendiente")
        headline_ejec = interp.get("headline") if tipo_interp == "auto_v2" else None
        diagnostico_ejec = interp.get("diagnostico") if tipo_interp == "auto_v2" else None
        mensaje_legacy = interp.get("mensaje", "")
        if headline_ejec:
            contexto = headline_ejec
        elif mensaje_legacy and tipo_interp not in ("pendiente",) and len(mensaje_legacy) > 10:
            contexto = mensaje_legacy
        elif not tabular and ultimo_val is not None:
            ma12 = d.get("ma12_ult")
            if ma12 is not None:
                dir_txt = "por encima" if ultimo_val > ma12 else "por debajo"
                contexto = f"{ultimo_val:.1f}{unidad} ({periodo_ref}) · MA12 {ma12:.1f}{unidad} · {dir_txt} del promedio anual."
            else:
                contexto = f"Último dato disponible: {ultimo_val:.1f}{unidad} ({periodo_ref})."
        else:
            contexto = ""

        # Sparkline
        alerta_actual = d.get("alerta", "neutro")
        sparkline_svg = ""
        if not tabular:
            series_dict = d.get("series") or {}
            campo_raw = d.get("campoDefault")
            campo_label = _slabel(campo_raw) if campo_raw else None
            if campo_label and campo_label in series_dict:
                serie_vals = series_dict[campo_label]
            elif series_dict:
                serie_vals = list(series_dict.values())[0]
            else:
                serie_vals = []
            sparkline_svg = _sparkline_svg(serie_vals, alerta_actual)

        # Dirección para síntesis ejecutiva
        if delta is not None:
            dir_arrow = "↑" if delta > 0 else "↓"
        else:
            dir_arrow = "→"

        # Datos comprimidos para chart inline en reporte completo.
        chart_payload = None
        if not tabular:
            series_dict = d.get("series") or {}
            periodos_serie = (d.get("periodos") or [])[-60:]  # últimos 60 periodos
            campo_raw = d.get("campoDefault")
            campo_label = _slabel(campo_raw) if campo_raw else None
            if campo_label and campo_label in series_dict:
                serie_principal = series_dict[campo_label][-60:]
                serie_label = campo_label
            elif series_dict:
                serie_label = list(series_dict.keys())[0]
                serie_principal = list(series_dict.values())[0][-60:]
            else:
                serie_principal = []
                serie_label = ""
            ma12_serie = (d.get("ma12") or [])[-60:] if d.get("ma12") else None
            if serie_principal:
                chart_payload = {
                    "periodos": periodos_serie,
                    "serie_label": serie_label,
                    "serie_vals": serie_principal,
                    "ma12": ma12_serie,
                    "unidad": unidad,
                }

        # Parrafos del writer+verifier (para reporte completo)
        interp_parrafos = interp.get("parrafos", []) if tipo_interp == "auto_v2" else []

        publicados.append({
            "id": iid,
            "nombre": d.get("nombre", iid),
            "categoria": d.get("categoria") or "",
            "tema": TEMA_MAP.get(iid, d.get("categoria") or "Otros"),
            "frecuencia": frecuencia_map.get(iid, ""),
            "periodo_ref": periodo_ref,
            "fecha_pub": fecha_pub_display,
            "fecha_pub_iso": fecha_pub,
            "alerta": alerta_actual,
            "is_priority": iid in PRIORITY_IDS,
            "stat_valor": ctx.get("stat_valor", "—"),
            "stat_valor_num": stat_valor_num,
            "unidad_corta": unidad_corta,
            "stat_delta": stat_delta,
            "delta_sign": delta_sign,
            "dir_arrow": dir_arrow,
            "contexto": contexto,
            "headline": headline_ejec or "",
            "parrafos": interp_parrafos,
            "diagnostico": diagnostico_ejec or "",
            "sparkline_svg": sparkline_svg,
            "chart_payload": chart_payload,
            "inegi_strip": ctx.get("inegi_strip"),
        })

    # Ordenar: prioridad y severidad
    _alerta_order = {"rojo": 0, "amarillo": 1, "verde": 2, "neutro": 3}
    publicados.sort(key=lambda x: (_alerta_order.get(x["alerta"], 9), not x["is_priority"]))

    # --- Próximas publicaciones con agrupación temporal ---
    proximas: list[dict] = []
    for iid, cal in calendar.items():
        for p in cal.get("proximas_publicaciones", []) or []:
            try:
                dias_prox = (date.fromisoformat(p["fecha"]) - hoy).days
            except (ValueError, KeyError):
                continue
            if 0 < dias_prox <= 14:
                pub_dt = date.fromisoformat(p["fecha"])
                if dias_prox == 1:
                    grupo = "Mañana"
                elif dias_prox <= 5:
                    grupo = "Esta semana"
                else:
                    grupo = "Próxima semana"
                proximas.append({
                    "fecha_iso": p["fecha"],
                    "fecha_display": f"{pub_dt.day} {MESES[pub_dt.month - 1]}",
                    "dia_semana": DIAS_ES_ABR[pub_dt.weekday()],
                    "nombre": indicadores.get(iid, {}).get("nombre") or p.get("evento_ics", iid)[:60],
                    "frecuencia": frecuencia_map.get(iid, ""),
                    "grupo": grupo,
                    "dias": dias_prox,
                })
    proximas.sort(key=lambda x: x["fecha_iso"])
    seen_nombres: set[str] = set()
    proximas_dedup: list[dict] = []
    for p in proximas:
        if p["nombre"] not in seen_nombres:
            seen_nombres.add(p["nombre"])
            proximas_dedup.append(p)

    # --- Síntesis ejecutiva agrupada por tema ---
    temas_vistos: dict[str, list] = {}
    for ind in publicados:
        tema = ind["tema"]
        temas_vistos.setdefault(tema, []).append(ind)

    # Orden de temas para la síntesis
    TEMA_ORDEN = ["Inflación", "Actividad", "Empleo", "Consumo", "Manufactura",
                  "Construcción", "Sector externo", "Sentimiento", "Regional", "Otros"]
    resumen_sections: list[dict] = []
    for tema in TEMA_ORDEN:
        if tema not in temas_vistos:
            continue
        inds_tema = temas_vistos[tema]
        # Alerta más severa del grupo
        alerta_grupo = min(
            (i["alerta"] for i in inds_tema),
            key=lambda a: _alerta_order.get(a, 9)
        )
        # Flecha dominante: si hay más caídas, ↓; si hay más subidas, ↑; else →
        arrows = [i["dir_arrow"] for i in inds_tema]
        if arrows.count("↓") > arrows.count("↑"):
            dir_grupo = "↓"
        elif arrows.count("↑") > arrows.count("↓"):
            dir_grupo = "↑"
        else:
            dir_grupo = "→"

        # Headlines prioritarios del tema: priorizar indicadores con interpretación auto_v2.
        # Tomar máximo 2 headlines por tema, ordenados por severidad y prioridad.
        inds_con_headline = sorted(
            [i for i in inds_tema if i.get("headline")],
            key=lambda x: (_alerta_order.get(x["alerta"], 9), not x["is_priority"]),
        )
        headlines_tema = []
        for ind in inds_con_headline[:2]:
            headlines_tema.append({
                "alerta": ind["alerta"],
                "indicador": ind["nombre"],
                "id": ind["id"],
                "texto": ind["headline"],
            })

        # Fallback: si no hay headlines (writer pendiente), mantener bullets de cifras.
        bullets = []
        if not headlines_tema:
            for ind in inds_tema:
                val_txt = f"{ind['stat_valor_num']}{ind['unidad_corta']}" if ind["stat_valor_num"] != "—" else ""
                delta_txt = f" ({ind['stat_delta']})" if ind["stat_delta"] != "—" else ""
                bullets.append({
                    "alerta": ind["alerta"],
                    "texto": f"{ind['nombre']}: {val_txt}{delta_txt}".strip(": "),
                })

        resumen_sections.append({
            "tema": tema,
            "dir": dir_grupo,
            "alerta": alerta_grupo,
            "headlines": headlines_tema,
            "bullets": bullets,
            "n_indicadores": len(inds_tema),
        })

    # --- Estado agregado semanal ---
    n_rojo = sum(1 for p in publicados if p["alerta"] == "rojo")
    n_amarillo = sum(1 for p in publicados if p["alerta"] == "amarillo")
    n_verde = sum(1 for p in publicados if p["alerta"] == "verde")
    n_total = len(publicados)
    if n_rojo >= 3:
        estado_texto = "Deterioro amplio"
        estado_detalle = f"{n_rojo} indicadores fuera de banda"
        estado_alerta = "rojo"
    elif n_rojo >= 1 and n_amarillo >= 1:
        estado_texto = "Presiones concentradas"
        estado_detalle = f"{n_rojo} en alerta · {n_amarillo} en vigilancia"
        estado_alerta = "amarillo"
    elif n_amarillo >= 2:
        estado_texto = "Señales mixtas"
        estado_detalle = f"{n_amarillo} indicadores en zona de vigilancia"
        estado_alerta = "amarillo"
    elif n_verde == n_total and n_total > 0:
        estado_texto = "Condiciones estables"
        estado_detalle = f"{n_verde} indicadores dentro de parámetros"
        estado_alerta = "verde"
    else:
        estado_texto = "Sin señales de alerta"
        estado_detalle = f"{n_total} publicaciones revisadas"
        estado_alerta = "neutro"
    estado_agregado = {"texto": estado_texto, "detalle": estado_detalle, "alerta": estado_alerta}

    # --- Etiqueta de semana ---
    lunes = hoy - timedelta(days=hoy.weekday())
    viernes = lunes + timedelta(days=4)
    semana_label = (
        f"{lunes.day}–{viernes.day} {MESES[viernes.month - 1].capitalize()} {viernes.year}"
        if lunes.month == viernes.month
        else f"{lunes.day} {MESES[lunes.month - 1]} – {viernes.day} {MESES[viernes.month - 1]} {viernes.year}"
    )

    meses_full = ["enero","febrero","marzo","abril","mayo","junio",
                  "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    build_fecha = f"{hoy.day} de {meses_full[hoy.month - 1]} de {hoy.year}"

    # Pre-computar grupos de próximas publicaciones para el template
    _prox_slice = proximas_dedup[:16]
    proximas_grupos: list[dict] = []
    _grupo_map: dict[str, list] = {}
    for _p in _prox_slice:
        _g = _p["grupo"]
        if _g not in _grupo_map:
            _grupo_map[_g] = []
        _grupo_map[_g].append(_p)
    _orden_grupos = ["Mañana", "Esta semana", "Próxima semana"]
    for _g in _orden_grupos:
        if _g in _grupo_map:
            proximas_grupos.append({"label": _g, "publicaciones": _grupo_map[_g]})
    # Agregar grupos inesperados al final
    for _g, _items in _grupo_map.items():
        if _g not in _orden_grupos:
            proximas_grupos.append({"label": _g, "publicaciones": _items})

    # Agrupar publicados por tema en TEMA_ORDEN para la vista de categorías
    _tema_dict: dict[str, list] = {}
    for _ind in publicados:
        _tema_dict.setdefault(_ind["tema"], []).append(_ind)
    publicados_by_tema: list[dict] = []
    for _tema in TEMA_ORDEN:
        if _tema in _tema_dict:
            publicados_by_tema.append({"tema": _tema, "inds": _tema_dict[_tema]})
    for _tema, _items in _tema_dict.items():
        if _tema not in TEMA_ORDEN:
            publicados_by_tema.append({"tema": _tema, "inds": _items})

    ctx_reporte = dict(
        semana_label=semana_label,
        publicados=publicados,
        publicados_by_tema=publicados_by_tema,
        proximas=_prox_slice,
        proximas_grupos=proximas_grupos,
        resumen_sections=resumen_sections,
        estado_agregado=estado_agregado,
        n_publicados=len(publicados),
        build_fecha=build_fecha,
        asset_prefix="",
    )

    tmpl = env.get_template("reporte_semanal.html.j2")
    out = tmpl.render(**ctx_reporte)
    (SITE_DIR / "reporte_semanal.html").write_text(out, encoding="utf-8")
    log.info("Reporte semanal OK · %d publicados · output: %s", len(publicados), SITE_DIR / "reporte_semanal.html")

    # Versión completa para PDF: ventana "rolling lunes a hoy".
    # Si hoy es lunes o martes, retrocede al lunes anterior (cubre la semana pasada completa).
    # Si hoy es miércoles a domingo, usa el lunes de la semana en curso.
    try:
        weekday = hoy.weekday()  # 0=lunes ... 6=domingo
        if weekday <= 1:
            lunes_relevante = hoy - timedelta(days=weekday + 7)
        else:
            lunes_relevante = hoy - timedelta(days=weekday)

        publicados_pdf = []
        for ind in publicados:
            fp_iso = ind.get("fecha_pub_iso")
            try:
                fp_dt = date.fromisoformat(fp_iso) if fp_iso else None
            except Exception:
                fp_dt = None
            # Antes se incluía fp_dt None incondicionalmente: un indicador con
            # fecha no parseable aparecía en TODOS los PDF semanales. Ahora se
            # exige fecha válida dentro de [lunes_relevante, hoy].
            if fp_dt is not None and lunes_relevante <= fp_dt <= hoy:
                publicados_pdf.append(ind)

        # Filtrar duplicados: si el indicador pleno y su versión resumen aparecen
        # en la misma ventana, conservar solo el pleno. Lee catálogo crudo
        # para acceder al campo "vinculado_con".
        ids_en_ventana = {p["id"] for p in publicados_pdf}
        duplicados_a_suprimir: set[str] = set()
        try:
            _catalog_raw = json.loads(
                (ROOT / "config" / "indicators.json").read_text(encoding="utf-8")
            ).get("indicadores", [])
            # Resolver cadenas transitivas: p. ej. pib_estatal → pib_anual →
            # pib_trimestral. Si algún eslabón de la cadena está en la ventana,
            # se suprime el resumen aunque su vínculo directo no esté presente.
            _vinc_map = {
                _c.get("id"): _c.get("vinculado_con")
                for _c in _catalog_raw if _c.get("id")
            }
            for _iid in ids_en_ventana:
                _seen = {_iid}
                _cur = _vinc_map.get(_iid)
                while _cur and _cur not in _seen:
                    if _cur in ids_en_ventana:
                        duplicados_a_suprimir.add(_iid)
                        break
                    _seen.add(_cur)
                    _cur = _vinc_map.get(_cur)
        except Exception as _e:
            log.warning("PDF: no pude leer catálogo crudo para deduplicar: %s", _e)
        if duplicados_a_suprimir:
            publicados_pdf = [p for p in publicados_pdf if p["id"] not in duplicados_a_suprimir]
            log.info("PDF: suprimidos %d duplicados vinculados: %s",
                     len(duplicados_a_suprimir), sorted(duplicados_a_suprimir))

        # Reconstruir síntesis ejecutiva basada únicamente en los publicados de la ventana PDF.
        _temas_pdf: dict[str, list] = {}
        for _ind in publicados_pdf:
            _temas_pdf.setdefault(_ind["tema"], []).append(_ind)
        resumen_sections_pdf: list[dict] = []
        for _tema in TEMA_ORDEN:
            if _tema not in _temas_pdf:
                continue
            _inds_tema = _temas_pdf[_tema]
            _alerta_grupo = min(
                (i["alerta"] for i in _inds_tema),
                key=lambda a: _alerta_order.get(a, 9),
            )
            _arrows = [i["dir_arrow"] for i in _inds_tema]
            if _arrows.count("↓") > _arrows.count("↑"):
                _dir_grupo = "↓"
            elif _arrows.count("↑") > _arrows.count("↓"):
                _dir_grupo = "↑"
            else:
                _dir_grupo = "→"
            _inds_hl = sorted(
                [i for i in _inds_tema if i.get("headline")],
                key=lambda x: (_alerta_order.get(x["alerta"], 9), not x["is_priority"]),
            )
            _headlines_tema = []
            for _ind in _inds_hl[:2]:
                _headlines_tema.append({
                    "alerta": _ind["alerta"],
                    "indicador": _ind["nombre"],
                    "id": _ind["id"],
                    "texto": _ind["headline"],
                })
            resumen_sections_pdf.append({
                "tema": _tema,
                "dir": _dir_grupo,
                "alerta": _alerta_grupo,
                "headlines": _headlines_tema,
                "bullets": [],
                "n_indicadores": len(_inds_tema),
            })

        ctx_pdf = dict(ctx_reporte)
        ctx_pdf["publicados"] = publicados_pdf
        ctx_pdf["n_publicados"] = len(publicados_pdf)
        ctx_pdf["resumen_sections"] = resumen_sections_pdf
        # Etiqueta de ventana para el header del reporte completo
        ctx_pdf["ventana_label"] = (
            f"Publicaciones del {lunes_relevante.day} {MESES[lunes_relevante.month - 1]} "
            f"al {hoy.day} {MESES[hoy.month - 1]} {hoy.year}"
        )

        tmpl_full = env.get_template("reporte_semanal_completo.html.j2")
        out_full = tmpl_full.render(**ctx_pdf)
        (SITE_DIR / "reporte_semanal_completo.html").write_text(out_full, encoding="utf-8")
        log.info("Reporte semanal completo OK · %d publicados (lunes %s a hoy) · output: %s",
                 len(publicados_pdf), lunes_relevante.isoformat(),
                 SITE_DIR / "reporte_semanal_completo.html")
    except Exception as e:
        log.warning("Reporte semanal completo no se generó: %s", e)


# ------------- copia de assets + build -------------

def copy_assets() -> None:
    dst = SITE_DIR / "assets"
    dst.mkdir(parents=True, exist_ok=True)
    for name in ("styles.css", "app.js"):
        src = ASSETS_DIR / name
        if src.exists():
            shutil.copy2(src, dst / name)
    # Explorador IMSS (HTML autocontenido externo, se sirve como página estática)
    explorador_src = ROOT / "docs" / "referencias" / "imss_referencia_rediseño.html"
    explorador_dst = SITE_DIR / "imss_explorador.html"
    if explorador_src.exists():
        if explorador_dst.exists():
            try:
                explorador_dst.chmod(0o644)
                explorador_dst.unlink()
            except Exception as exc:
                log.warning("No pude borrar %s: %s", explorador_dst, exc)
        try:
            shutil.copy(explorador_src, explorador_dst)
            explorador_dst.chmod(0o644)
            log.info("Copiado explorador IMSS: %s", explorador_dst.relative_to(ROOT))
        except Exception as exc:
            log.warning("No pude copiar explorador IMSS: %s", exc)


def export_csvs() -> None:
    """Genera site/data/{iid}.csv para cada indicador + tabla_resumen.csv consolidado."""
    import csv
    csv_dir = SITE_DIR / "data"
    csv_dir.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "data").glob("*.json"):
        iid = f.stem
        if iid in {"catalog", "home_synthesis", "interpretations"}:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = d.get("series", []) or []
        if not rows or not isinstance(rows[0], dict):
            continue
        cols = d.get("columnas_normalizadas") or list(rows[0].keys())
        out_file = csv_dir / f"{iid}.csv"
        with out_file.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})


def export_search_index(indicadores: dict) -> None:
    """Genera site/data/search-index.json para búsqueda global del header."""
    index = []
    for iid, d in indicadores.items():
        nombre = d.get("_label_tabla") or d.get("nombre", iid)
        categoria = d.get("categoria", "")
        unidad = d.get("unidad", "")
        # Etiquetas adicionales para mejorar matching
        keywords = []
        if categoria:
            keywords.append(categoria.lower())
        # Sinónimos comunes
        synonyms = {
            "igae": ["actividad", "actividad económica", "indicador global"],
            "inpc_mensual": ["inflación", "precios al consumidor", "INPC"],
            "inpc_quincenal": ["inflación quincenal", "INPC 1Q", "INPC 2Q"],
            "inpp": ["productor", "precios al productor"],
            "balanza_comercial": ["exportaciones", "importaciones", "saldo comercial", "FOB"],
            "enoe_mensual": ["desocupación", "desempleo", "tasa de desocupación", "ocupación"],
            "enoe_trimestral": ["empleo trimestral", "PEA"],
            "fbcf": ["inversión", "formación bruta capital fijo"],
            "consumo_privado": ["consumo", "gasto hogares"],
            "confianza_consumidor": ["ICC", "confianza"],
            "emoe_ipm": ["IPM", "pedidos manufactureros"],
            "emoe_ice": ["ICE", "confianza empresarial"],
            "emoe_iat": ["IAT", "tendencia"],
            "actividad_industrial": ["IMAI", "industrial", "manufactura"],
            "ind_ciclicos": ["coincidente", "adelantado", "ciclos"],
            "pib_trimestral": ["PIB"],
            "pib_anual": ["PIB anual"],
            "comercio_mayoreo": ["mayoreo", "EMEC mayoreo"],
            "comercio_menudeo": ["menudeo", "EMEC menudeo"],
            "servicios": ["EMS", "servicios"],
            "emim": ["EMIM", "manufactura"],
            "enec": ["construcción", "ENEC"],
            "autos_ligeros": ["automotriz ligeros", "vehículos ligeros"],
            "autos_pesados": ["automotriz pesados", "vehículos pesados"],
            "pib_estatal": ["PIB estatal", "entidades", "estados"],
            "itaee_estatal": ["ITAEE", "trimestral estatal"],
            "imai_estatal": ["IMAI estatal", "industrial por estado"],
            "export_entidad": ["exportaciones por estado", "exportaciones entidad"],
        }
        keywords.extend(synonyms.get(iid, []))
        index.append({
            "id": iid,
            "nombre": nombre,
            "categoria": categoria,
            "unidad": unidad,
            "keywords": keywords,
            "url": f"indicador/{iid}.html",
        })
    out = SITE_DIR / "data" / "search-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def export_tabla_resumen(indicadores: dict) -> None:
    """Genera site/data/tabla_resumen.csv con último valor de cada indicador."""
    import csv
    out_file = SITE_DIR / "data" / "tabla_resumen.csv"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with out_file.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["indicador", "categoria", "periodo", "valor", "unidad", "delta_vs_previo", "frecuencia"])
        for iid, d in indicadores.items():
            nombre = d.get("_label_tabla") or d.get("nombre", iid)
            categoria = d.get("categoria", "")
            periodo = d.get("_periodo_tabular") if d.get("tabular") else (d.get("periodos") or ["—"])[-1]
            ultimo = d.get("ultimo")
            unidad = d.get("unidad", "")
            delta = d.get("delta")
            frecuencia = d.get("frecuencia", "")
            writer.writerow([
                nombre, categoria, periodo or "",
                f"{ultimo:.4f}" if isinstance(ultimo, (int, float)) else "",
                unidad,
                f"{delta:+.4f}" if isinstance(delta, (int, float)) else "",
                frecuencia,
            ])


# ---------- v3 builders (paralelos) ----------

KPI_V3 = [
    {
        "id": "inpc_mensual", "etiqueta": "Inflación general",
        "icon_svg": '<path d="M3 17l6-6 4 4 8-8" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 7h7v7" stroke-width="2.4" stroke-linecap="round"/>',
        "icon_color": "#9B2247", "campo_principal": "INPC_Anual",
        "unidad": "%", "etiqueta_unidad": "variación anual", "color_valor": "#9B2247",
    },
    {
        "id": "igae", "etiqueta": "Actividad económica",
        "icon_svg": '<rect x="3" y="13" width="3.5" height="8" rx="1" stroke-width="2"/><rect x="9" y="9" width="3.5" height="12" rx="1" stroke-width="2"/><rect x="15" y="5" width="3.5" height="16" rx="1" stroke-width="2"/>',
        "icon_color": "#003057", "campo_principal": "Total_Mensual",
        "unidad": "%", "etiqueta_unidad": "variación mensual", "color_valor": "#003057",
    },
    {
        "id": "balanza_comercial", "etiqueta": "Saldo balanza comercial",
        "icon_svg": '<circle cx="12" cy="12" r="9" stroke-width="2"/><path d="M3 12h18M12 3a13 13 0 010 18M12 3a13 13 0 000 18" stroke-width="2"/>',
        "icon_color": "#08989C", "campo_principal": "Saldo_total_MDD",
        "unidad": "MDD", "etiqueta_unidad": "saldo desestacionalizado", "color_valor": "#08989C",
    },
    {
        "id": "confianza_consumidor", "etiqueta": "Confianza del consumidor",
        "icon_svg": '<circle cx="9" cy="8" r="3" stroke-width="2"/><circle cx="17" cy="9" r="2.5" stroke-width="2"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M14 20c0-2.5 2-4.5 4.5-4.5S23 17.5 23 20" stroke-width="2"/>',
        "icon_color": "#9B2247", "campo_principal": "Anual",
        "unidad": "pts", "etiqueta_unidad": "diferencia anual", "color_valor": "#9B2247",
    },
    {
        "id": "enoe_mensual", "etiqueta": "Tasa de desocupación",
        "icon_svg": '<rect x="3" y="7" width="18" height="13" rx="2" stroke-width="2"/><path d="M9 7V5a3 3 0 016 0v2M3 12h18" stroke-width="2"/>',
        "icon_color": "#08989C", "campo_principal": "Tasa_desocupacion_Total",
        "unidad": "%", "etiqueta_unidad": "tasa nacional", "color_valor": "#08989C",
    },
    {
        "id": "empleo_imss", "etiqueta": "Empleo formal IMSS",
        "icon_svg": '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="7" r="4" stroke-width="2"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" stroke-width="2" stroke-linecap="round"/>',
        "icon_color": "#003057", "campo_principal": "_total_abs",
        "unidad": "M", "etiqueta_unidad": "puestos afiliados", "color_valor": "#003057",
    },
]

MESES_V3 = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MESES_FULL_V3 = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _v3_periodo_paren(periodo: str) -> str:
    if not periodo or "-" not in periodo:
        return ""
    parts = periodo.split("-")
    if len(parts) != 2:
        return ""
    head, yy = parts
    try:
        yyy = 2000 + int(yy) if int(yy) <= 30 else 1900 + int(yy)
        return f"({head} {yyy})"
    except Exception:
        return ""


def _v3_get_kpi_data(cfg: dict) -> dict:
    data_file = ROOT / "data" / f"{cfg['id']}.json"
    out = {"valor": None, "periodo": None, "delta": None, "delta_periodo": None}
    if not data_file.exists():
        return out
    raw = json.loads(data_file.read_text(encoding="utf-8"))
    campo = cfg["campo_principal"]
    # Campo especial: total absoluto en millones + género (empleo_imss)
    if campo == "_total_abs":
        rows    = raw.get("series", []) or []
        periodos_raw = raw.get("periodos", []) or []
        if rows:
            last = rows[-1]
            total = last.get("Total")
            hom   = last.get("Hombres")
            muj   = last.get("Mujeres")
            out["valor"]  = round(total / 1e6, 2) if total else None
            out["periodo"] = periodos_raw[-1] if periodos_raw else None
            if len(rows) > 1:
                prev_total = rows[-2].get("Total")
                if prev_total and total:
                    out["delta"] = round((total - prev_total) / 1e6, 2)
                    out["delta_periodo"] = periodos_raw[-2] if len(periodos_raw) > 1 else None
            if total and hom and muj:
                out["hom_pct"] = round(hom / total * 100, 1)
                out["muj_pct"] = round(muj / total * 100, 1)
        return out
    # Campo especial: leer desde series_nacional_yoy (empleo_imss)
    if campo == "_nac_yoy":
        yoy = raw.get("series_nacional_yoy", {})
        valores  = yoy.get("var_anual", []) or []
        periodos = yoy.get("periodos", []) or []
        if valores:
            out["valor"]  = valores[-1]
            out["periodo"] = periodos[-1] if periodos else None
            if len(valores) > 1:
                out["delta"] = round(valores[-1] - valores[-2], 2)
                out["delta_periodo"] = periodos[-2] if len(periodos) > 1 else None
        return out
    rows = raw.get("series", []) or []
    periodos = raw.get("periodos", []) or []
    if not rows or not isinstance(rows[0], dict):
        return out
    for i in range(len(rows) - 1, -1, -1):
        v = rows[i].get(campo)
        if v is not None:
            out["valor"] = v
            out["periodo"] = periodos[i] if i < len(periodos) else None
            if i > 0:
                v_prev = rows[i - 1].get(campo)
                if v_prev is not None:
                    out["delta"] = round(v - v_prev, 2)
                    out["delta_periodo"] = periodos[i - 1] if (i - 1) < len(periodos) else None
            break
    return out


def _v3_build_kpis() -> list[dict]:
    kpis = []
    for cfg in KPI_V3:
        info = _v3_get_kpi_data(cfg)
        valor = info["valor"]
        periodo = info["periodo"]
        delta = info["delta"]
        delta_periodo = info["delta_periodo"]
        if cfg["unidad"] == "MDD":
            valor_fmt = f"{valor:,.0f}" if valor is not None else "—"
        else:
            valor_fmt = f"{valor:.2f}" if valor is not None else "—"
        delta_dir = "up" if (delta or 0) > 0 else ("down" if (delta or 0) < 0 else "flat")
        delta_arrow = "↑" if delta_dir == "up" else ("↓" if delta_dir == "down" else "→")
        if cfg["id"] in ("inpc_mensual", "enoe_mensual"):
            verbo = "Subió" if delta_dir == "up" else ("Bajó" if delta_dir == "down" else "Sin cambio")
        else:
            verbo = "Creció" if delta_dir == "up" else ("Disminuyó" if delta_dir == "down" else "Sin cambio")
        delta_unidad = "pp" if cfg["unidad"] == "%" else cfg["unidad"]
        delta_abs_fmt = f"{abs(delta):.2f}" if delta is not None else "—"
        delta_periodo_label = _v3_periodo_paren(delta_periodo or "").replace("(", "").replace(")", "")
        kpi_entry = {
            **cfg,
            "valor_fmt": valor_fmt,
            "periodo_label": _v3_periodo_paren(periodo or ""),
            "delta_dir": delta_dir,
            "delta_arrow": delta_arrow,
            "delta_texto": f"{verbo} {delta_abs_fmt} {delta_unidad}",
            "delta_periodo_label": delta_periodo_label,
        }
        if info.get("hom_pct") is not None:
            kpi_entry["hom_pct"] = info["hom_pct"]
            kpi_entry["muj_pct"] = info["muj_pct"]
        kpis.append(kpi_entry)
    return kpis


def _v3_build_publicaciones(calendar: dict, hoy_iso: str) -> list[dict]:
    eventos = []
    for iid, cal in calendar.items():
        for p in cal.get("proximas_publicaciones", []) or []:
            fecha = p["fecha"]
            if fecha >= hoy_iso:
                eventos.append({
                    "iid": iid,
                    "nombre": cal.get("nombre", iid),
                    "fecha": fecha,
                    "es_hoy": fecha == hoy_iso,
                })
    eventos.sort(key=lambda e: e["fecha"])
    eventos = eventos[:6]
    out = []
    for ev in eventos:
        try:
            y, m, d = ev["fecha"].split("-")
            fecha_label = f"{int(d)} {MESES_V3[int(m) - 1]} {y}"
        except Exception:
            fecha_label = ev["fecha"]
        out.append({
            **ev,
            "hora": "08:00 h",
            "fecha_label": fecha_label,
        })
    return out


def _v3_build_tabla(indicadores: dict) -> list[dict]:
    top_ids = ["inpc_mensual", "igae", "balanza_comercial", "confianza_consumidor",
               "enoe_mensual", "empleo_imss", "actividad_industrial", "fbcf", "consumo_privado",
               "comercio_menudeo", "servicios", "emim", "enec"]
    rows = []
    for iid in top_ids:
        d = indicadores.get(iid)
        if not d:
            continue
        nombre = d.get("nombre", iid) if iid == "empleo_imss" else (d.get("_label_tabla") or d.get("nombre", iid))
        periodo = d.get("_periodo_tabular") if d.get("tabular") else (d.get("periodos") or ["—"])[-1]
        ultimo = d.get("ultimo")
        delta = d.get("delta")
        unidad = d.get("unidad", "")
        # empleo_imss: mostrar total en M y delta mensual en %
        if iid == "empleo_imss":
            valor_fmt = (f"{ultimo:.1f} M" if ultimo is not None else "—")
            delta_unidad_lab = "%"
            delta_fmt = f"{delta:+.2f}%" if delta is not None else "—"
            var_label = "Mensual"
        else:
            valor_fmt = (f"{ultimo:.2f}" if ultimo is not None else "—") + (" %" if unidad == "%" else (f" {unidad}" if unidad else ""))
            delta_unidad_lab = "pp" if unidad == "%" else unidad
            delta_fmt = f"{delta:+.2f} {delta_unidad_lab}" if delta is not None else "—"
            var_label = "Anual" if (d.get("campoDefault") or "").endswith("Anual") else "Mensual"
        delta_dir = "up" if (delta or 0) > 0 else ("down" if (delta or 0) < 0 else "flat")
        delta_arrow = "↑" if delta_dir == "up" else ("↓" if delta_dir == "down" else "→")
        href = "imss_explorador.html" if iid == "empleo_imss" else f"indicador/{iid}.html"
        rows.append({
            "iid": iid,
            "nombre": nombre,
            "href": href,
            "periodo_label": _v3_periodo_paren(periodo).replace("(", "").replace(")", "") if periodo else "—",
            "valor_fmt": valor_fmt,
            "delta_dir": delta_dir,
            "delta_arrow": delta_arrow,
            "delta_fmt": delta_fmt,
            "var_label": var_label,
            "categoria": (d.get("categoria") or "").lower(),
        })
    return rows


def _v3_build_sparks(indicadores: dict, top_ids: list[str]) -> dict:
    sparks = {}
    for iid in top_ids:
        d = indicadores.get(iid) or {}
        if d.get("tabular"):
            continue
        campo = d.get("campoDefault")
        if not campo:
            continue
        data_file = ROOT / "data" / f"{iid}.json"
        if not data_file.exists():
            continue
        raw = json.loads(data_file.read_text(encoding="utf-8"))
        rows = raw.get("series", []) or []
        if rows and isinstance(rows[0], dict):
            serie = [r.get(campo) for r in rows][-36:]
        else:
            serie = []
        delta = d.get("delta") or 0
        dir_ = "up" if delta > 0 else ("down" if delta < 0 else "flat")
        sparks[iid] = {"serie36": serie, "dir": dir_}
    return sparks


# ─────────────────────────────────────────────────────────────────────────────
# Home v2 helpers: sparklines SVG inline, hero chart, category groups
# ─────────────────────────────────────────────────────────────────────────────

_MESES_ES = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
_CAT_ORDER = [
    ("macro",               "Macro"),
    ("precios",             "Precios"),
    ("actividad",           "Actividad"),
    ("encuestas_sectoriales", "Encuestas sectoriales"),
    ("automotriz",          "Automotriz"),
    ("empleo",              "Empleo"),
    ("regional",            "Regional"),
    ("sentimiento",         "Sentimiento"),
]
_COLOR_POS = "#16A34A"
_COLOR_NEG = "#DC2626"
_COLOR_FLAT = "#71717A"


def _v3_sparkline_svg(serie: list, dir_: str, w: int = 90, h: int = 26) -> str:
    """Retorna SVG <polyline> con baseline (cero o min) y dot final.
    Si la serie cruza cero, dibuja línea horizontal en y=0.
    Si no, dibuja una línea tenue en el mínimo de la serie como ancla visual."""
    vals = [v for v in serie if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rang = hi - lo if hi != lo else 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = round(i / (n - 1) * w, 1)
        y = round((h - 2) - ((v - lo) / rang) * (h - 4) + 1, 1)
        pts.append(f"{x},{y}")
    # Baseline: zero si la serie cruza, sino min
    crosses_zero = lo < 0 < hi
    if crosses_zero:
        y_base = round((h - 2) - ((0 - lo) / rang) * (h - 4) + 1, 1)
        base_stroke = "#9CA3AF"
        base_dash = "2,2"
    else:
        y_base = h - 2 + 1
        base_stroke = "#E4E4E7"
        base_dash = ""
    color = _COLOR_POS if dir_ == "up" else (_COLOR_NEG if dir_ == "down" else _COLOR_FLAT)
    last_x, last_y = pts[-1].split(",")
    dash_attr = f' stroke-dasharray="{base_dash}"' if base_dash else ""
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<line x1="0" y1="{y_base}" x2="{w}" y2="{y_base}" stroke="{base_stroke}" stroke-width="0.6"{dash_attr}/>'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="1.6" fill="{color}"/>'
        f'</svg>'
    )


def _v3_fmt_periodo_label(p: str) -> str:
    """'M01-25' → 'ENE 2025', 'T1-25' → 'T1 2025'."""
    if not p or "-" not in p:
        return p or ""
    head, tail = p.split("-", 1)
    try:
        yy = int(tail)
        yyyy = 2000 + yy if yy <= 30 else 1900 + yy
    except ValueError:
        return p
    head_clean = head.lstrip("M").lstrip("T")
    try:
        mm = int(head_clean[:2]) if len(head_clean) >= 2 else int(head_clean)
        if 1 <= mm <= 12:
            return f"{_MESES_ES[mm - 1]} {yyyy}"
    except ValueError:
        pass
    return f"{head} {yyyy}"


def _v3_build_hero(indicadores: dict) -> dict:
    """Extrae 24 meses del IGAE para el hero chart de la home."""
    d = indicadores.get("igae", {})
    campo = d.get("campoDefault")
    if not campo or d.get("tabular"):
        return {}
    data_file = ROOT / "data" / "igae.json"
    if not data_file.exists():
        return {}
    raw = json.loads(data_file.read_text(encoding="utf-8"))
    all_rows = raw.get("series", []) or []
    all_per = raw.get("periodos", []) or []
    if not all_rows or not isinstance(all_rows[0], dict):
        return {}
    N = 24
    serie = [r.get(campo) for r in all_rows][-N:]
    per_labels = all_per[-N:]
    vals = [v for v in serie if v is not None]
    if len(vals) < 2:
        return {}
    lo, hi = min(vals), max(vals)
    rang = hi - lo if hi != lo else 1.0
    # SVG canvas: viewBox "0 0 580 110", usable x∈[20,560] y∈[10,100]
    X0, XN, Y0, YN = 20, 560, 10, 100
    W_SVG, H_SVG = XN - X0, YN - Y0
    n = len(serie)
    pts = []
    for i, v in enumerate(serie):
        if v is None:
            continue
        x = round(X0 + i / max(n - 1, 1) * W_SVG, 1)
        y = round(YN - ((v - lo) / rang) * H_SVG, 1)
        y = max(Y0, min(YN, y))
        pts.append(f"{x},{y}")
    last_x, last_y = (pts[-1].split(",") if pts else ["560", "55"])
    # Baseline: cero si la serie lo cruza, sino min como ancla visual.
    if lo < 0 < hi:
        y_zero = round(YN - ((0 - lo) / rang) * H_SVG, 1)
        zero_label = "0%"
    else:
        y_zero = YN  # min de la serie
        zero_label = f"{lo:+.1f}%"
    y_zero = max(Y0, min(YN, y_zero))
    # X axis labels: 5 evenly spaced
    x_labels = []
    idxs = sorted({0, n // 4, n // 2, 3 * n // 4, n - 1})
    for idx in idxs:
        if idx < len(per_labels):
            x = round(X0 + idx / max(n - 1, 1) * W_SVG, 1)
            x_labels.append({
                "x": x,
                "label": _v3_fmt_periodo_label(per_labels[idx]),
                "is_last": idx == n - 1,
            })
    ultimo = d.get("ultimo")
    delta = d.get("delta")
    delta_dir = "up" if (delta or 0) > 0 else ("down" if (delta or 0) < 0 else "flat")
    periodo = (d.get("periodos") or [""])[-1]
    # Texto accesible para screen readers.
    primer_label = _v3_fmt_periodo_label(per_labels[0]) if per_labels else ""
    ultimo_label = _v3_fmt_periodo_label(per_labels[-1]) if per_labels else ""
    dir_txt = "al alza" if delta_dir == "up" else ("a la baja" if delta_dir == "down" else "sin cambio relevante")
    aria_label = (
        f"IGAE, variación anual. Serie de {primer_label} a {ultimo_label}. "
        f"Tendencia {dir_txt}. Valor actual {ultimo:+.1f}% en {ultimo_label}." if ultimo is not None else
        f"IGAE, serie sin datos suficientes."
    )
    return {
        "pts": " ".join(pts),
        "last_x": last_x,
        "last_y": last_y,
        "y_zero": y_zero,
        "y_zero_label": zero_label,
        "x_labels": x_labels,
        "valor_fmt": f"{ultimo:+.1f}" if ultimo is not None else "—",
        "delta_dir": delta_dir,
        "delta_fmt": f"{delta:+.2f} pp" if delta is not None else "—",
        "periodo_label": _v3_periodo_paren(periodo).replace("(", "").replace(")", ""),
        "aria_label": aria_label,
        "ymin_fmt": f"{lo:+.1f}%",
        "ymax_fmt": f"{hi:+.1f}%",
    }


def _v3_row_fmt(iid: str, d: dict) -> dict:
    """Formatea una fila de indicador para cat_groups o tabla full."""
    ultimo = d.get("ultimo")
    delta = d.get("delta")
    unidad = d.get("unidad", "")
    nombre = d.get("nombre", iid)
    if iid == "empleo_imss":
        valor_fmt = f"{ultimo:.1f} M" if ultimo is not None else "—"
        delta_unidad = "%"
    elif unidad == "%":
        valor_fmt = f"{ultimo:.2f}%" if ultimo is not None else "—"
        delta_unidad = "pp"
    elif unidad == "MDD":
        valor_fmt = f"{ultimo:,.0f} MDD" if ultimo is not None else "—"
        delta_unidad = "MDD"
    elif unidad:
        valor_fmt = f"{ultimo:.2f} {unidad}" if ultimo is not None else "—"
        delta_unidad = unidad
    else:
        valor_fmt = f"{ultimo:.2f}" if ultimo is not None else "—"
        delta_unidad = ""
    delta_dir = "up" if (delta or 0) > 0 else ("down" if (delta or 0) < 0 else "flat")
    delta_arrow = "↑" if delta_dir == "up" else ("↓" if delta_dir == "down" else "→")
    if delta is not None:
        delta_fmt = f"{delta_arrow} {abs(delta):.2f} {delta_unidad}".strip()
    else:
        delta_fmt = "—"
    periodos = d.get("periodos") or []
    periodo_label = (
        _v3_periodo_paren(periodos[-1]).replace("(", "").replace(")", "")
        if periodos else "—"
    )
    href = "imss_explorador.html" if iid == "empleo_imss" else f"indicador/{iid}.html"
    return {
        "iid": iid,
        "nombre": nombre,
        "href": href,
        "valor_fmt": valor_fmt,
        "delta_dir": delta_dir,
        "delta_arrow": delta_arrow,
        "delta_fmt": delta_fmt,
        "periodo_label": periodo_label,
        "tabular": bool(d.get("tabular")),
    }


def _v3_build_cat_groups(indicadores: dict) -> list:
    """Agrupa los 32 indicadores por categoría con sparklines SVG inline."""
    groups = []
    for cat_id, cat_name in _CAT_ORDER:
        rows = []
        for iid, d in indicadores.items():
            if (d.get("categoria") or "").lower() != cat_id:
                continue
            row = _v3_row_fmt(iid, d)
            # Sparkline: solo para no-tabulares con campoDefault
            spark_svg = ""
            if not d.get("tabular"):
                campo = d.get("campoDefault")
                if campo:
                    data_file = ROOT / "data" / f"{iid}.json"
                    if data_file.exists():
                        try:
                            raw_data = json.loads(data_file.read_text(encoding="utf-8"))
                            r_rows = raw_data.get("series", []) or []
                            if r_rows and isinstance(r_rows[0], dict):
                                serie = [r.get(campo) for r in r_rows][-24:]
                                delta = d.get("delta") or 0
                                dir_ = "up" if delta > 0 else ("down" if delta < 0 else "flat")
                                spark_svg = _v3_sparkline_svg(serie, dir_)
                        except Exception:
                            pass
            row["spark_svg"] = spark_svg
            rows.append(row)
        if rows:
            groups.append({"id": cat_id, "nombre": cat_name, "rows": rows})
    return groups


def _v3_build_kpis_v2() -> list:
    """Igual que _v3_build_kpis pero añade spark_svg a cada KPI."""
    kpis = _v3_build_kpis()
    for kpi in kpis:
        iid = kpi["id"]
        campo = kpi.get("campo_principal")
        spark_svg = ""
        if campo and campo not in ("_total_abs", "_nac_yoy"):
            data_file = ROOT / "data" / f"{iid}.json"
            if data_file.exists():
                try:
                    raw_data = json.loads(data_file.read_text(encoding="utf-8"))
                    r_rows = raw_data.get("series", []) or []
                    if r_rows and isinstance(r_rows[0], dict):
                        serie = [r.get(campo) for r in r_rows][-24:]
                        dir_ = kpi.get("delta_dir", "flat")
                        spark_svg = _v3_sparkline_svg(serie, dir_)
                except Exception:
                    pass
        kpi["spark_svg"] = spark_svg
    return kpis


def build_comparar(env: Environment, indicadores: dict, hoy: date) -> None:
    """Genera site/comparar.html con 8 comparativas curadas."""
    tmpl = env.get_template("comparar.html.j2")
    meses_full = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    fecha_larga = f"{hoy.day} de {meses_full[hoy.month - 1]} de {hoy.year}"

    nav_groups = [{"label": lbl, "items": [
        {"id": iid, "label": lbl2, "href": href} for iid, lbl2, href in items
    ]} for lbl, items in NAV_STRUCTURE]

    # Cargar config de comparativas curadas
    cfg_path = ROOT / "config" / "comparativas.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    comparativas = cfg.get("comparativas", [])

    # Para cada comparativa, extraer las series concretas desde data/
    cmp_data = {}
    for c in comparativas:
        cid = c["id"]
        lookback = c.get("lookback_meses", 60)
        series_extracted = []
        union_periodos = []
        for s in c["series"]:
            iid = s["iid"]
            campo = s["campo"]
            raw_file = ROOT / "data" / f"{iid}.json"
            if not raw_file.exists():
                continue
            raw = json.loads(raw_file.read_text(encoding="utf-8"))
            rows = raw.get("series", []) or []
            periodos_raw = raw.get("periodos", []) or []
            if not rows or not isinstance(rows[0], dict):
                continue
            serie_full = [r.get(campo) for r in rows]
            N = min(lookback, len(serie_full))
            periodos = periodos_raw[-N:]
            serie = serie_full[-N:]
            series_extracted.append({
                "label": s["label"],
                "iid": iid,
                "periodos": periodos,
                "serie": serie,
            })
            if len(periodos) > len(union_periodos):
                union_periodos = periodos
        cmp_data[cid] = {
            "titulo": c["titulo"],
            "unidad": c.get("unidad", ""),
            "modo": c.get("modo", "raw"),
            "benchmark": c.get("benchmark"),
            "periodos": union_periodos,
            "series": series_extracted,
        }

    ctx = {
        "page_title": "Análisis comparativos",
        "asset_prefix": "",
        "active_section": "comparar",
        "active_id": "__compare__",
        "build_fecha": fecha_larga,
        "topbar_fecha": fecha_larga,
        "nav_groups": nav_groups,
        "comparativas": comparativas,
        "cmp_data_json": _json_for_script(cmp_data),
    }
    (SITE_DIR / "comparar.html").write_text(tmpl.render(**ctx), encoding="utf-8")


def build_v3(env: Environment, indicadores: dict, calendar: dict, hoy: date) -> None:
    """Genera site/index.html con la estética GobMx 2026."""
    tmpl = env.get_template("index.html.j2")
    hoy_iso = hoy.isoformat()
    fecha_larga = f"{hoy.day} de {MESES_FULL_V3[hoy.month - 1]} de {hoy.year}"

    nav_groups_v3 = [{"label": lbl, "items": [
        {"id": iid, "label": lbl2, "href": href} for iid, lbl2, href in items
    ]} for lbl, items in NAV_STRUCTURE]

    kpis = _v3_build_kpis_v2()
    publicaciones = _v3_build_publicaciones(calendar, hoy_iso)
    tabla_rows = _v3_build_tabla(indicadores)
    hero = _v3_build_hero(indicadores)
    cat_groups = _v3_build_cat_groups(indicadores)

    synthesis: dict = {}
    synth_path = ROOT / "data" / "home_synthesis.json"
    if synth_path.exists():
        try:
            synthesis = json.loads(synth_path.read_text(encoding="utf-8"))
        except Exception:
            synthesis = {}

    ctx = {
        "page_title": "Panorama económico de México",
        "asset_prefix": "",
        "active_section": "inicio",
        "active_id": "__home__",
        "build_fecha": fecha_larga,
        "topbar_fecha": fecha_larga,
        "nav_groups": nav_groups_v3,
        "kpis": kpis,
        "publicaciones": publicaciones,
        "tabla_rows": tabla_rows,
        "hero": hero,
        "cat_groups": cat_groups,
        "synthesis": synthesis,
    }
    (SITE_DIR / "index.html").write_text(tmpl.render(**ctx), encoding="utf-8")


def main() -> None:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    indicadores, calendar, thresholds = load_all(ROOT)
    if not indicadores:
        raise RuntimeError(f"No se encontraron data/*.json normalizables en {ROOT / 'data'}")

    hoy = _hoy_mx()
    cal_ctx = build_calendar_context(calendar, indicadores, hoy)
    build_fecha = hoy.isoformat()

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "indicador").mkdir(parents=True, exist_ok=True)
    copy_assets()
    export_csvs()
    export_tabla_resumen(indicadores)
    export_search_index(indicadores)
    # Copiar glossary al sitio para fetch desde JS
    glossary_src = ROOT / "config" / "glossary.json"
    if glossary_src.exists():
        shutil.copy2(glossary_src, SITE_DIR / "data" / "glossary.json")

    # --- index (estética GobMx 2026) ---
    build_v3(env, indicadores, calendar, hoy)
    build_comparar(env, indicadores, hoy)
    build_reporte_semanal(env, indicadores, calendar, thresholds, hoy)

    # --- indicador/<id>.html ---
    tmpl_det = env.get_template("indicador.html.j2")
    # Cargar configs de presentación una vez
    benchmarks_path = ROOT / "config" / "benchmarks.json"
    eventos_path = ROOT / "config" / "eventos_macro.json"
    benchmarks_cfg = json.loads(benchmarks_path.read_text(encoding="utf-8"))["indicadores"] if benchmarks_path.exists() else {}
    eventos_cfg = json.loads(eventos_path.read_text(encoding="utf-8"))["eventos"] if eventos_path.exists() else []

    for iid, d in indicadores.items():
        # empleo_imss vive como sección dedicada del sidebar (imss_explorador.html).
        # Skip la generación del detalle estándar.
        if iid == "empleo_imss":
            continue
        d_ctx = build_indicador_ctx(d, iid=iid, thresholds=thresholds)
        # Cargar serie COMPLETA del raw para permitir selector de rango
        raw_file = ROOT / "data" / f"{iid}.json"
        periodos_chart = d.get("periodos_long") or d.get("periodos") or []
        series_chart = d.get("series_long") or d.get("series") or {}
        ma12_chart = d.get("ma12_long") or d.get("ma12") or []
        if not d.get("tabular") and raw_file.exists():
            try:
                raw = json.loads(raw_file.read_text(encoding="utf-8"))
                rows = raw.get("series", []) or []
                periodos_full = raw.get("periodos", []) or []
                if rows and isinstance(rows[0], dict) and len(periodos_full) > len(periodos_chart):
                    # Serie completa por columna
                    cols_to_keep = list(series_chart.keys()) if isinstance(series_chart, dict) else []
                    serie_full = {}
                    # Mapear etiqueta del normalize → campo raw (best effort)
                    campo_to_label = {}
                    if cols_to_keep:
                        # Heurística: si solo hay 1-3 series, intentamos campoDefault y secs
                        principal = d.get("campoDefault")
                        if principal and principal in rows[0]:
                            campo_to_label[principal] = list(series_chart.keys())[0]
                    # Si no hay map por label, usamos directamente los campos del raw que coincidan con keys
                    # Construir series_full usando los nombres del normalize
                    import sys as _s
                    _s.path.insert(0, str(SCRIPTS / "normalize.py".replace("normalize.py", ""))) if False else None
                    from normalize import serie_label
                    series_full = {}
                    for raw_key in rows[0].keys():
                        if raw_key in ("Periodo", "Mes", "Trimestre"):
                            continue
                        lbl = serie_label(raw_key)
                        if lbl in series_chart:
                            series_full[lbl] = [r.get(raw_key) for r in rows]
                    if series_full:
                        series_chart = series_full
                        periodos_chart = periodos_full
                        # Recalcular MA12 sobre serie completa
                        principal_lbl = list(series_chart.keys())[0]
                        ma_serie = series_chart[principal_lbl]
                        ma_full = []
                        for i in range(len(ma_serie)):
                            if i < 11:
                                ma_full.append(None)
                            else:
                                vent = [v for v in ma_serie[i-11:i+1] if v is not None]
                                ma_full.append(round(sum(vent)/12, 2) if len(vent) == 12 else None)
                        ma12_chart = ma_full
            except Exception:
                pass
        indic_payload = {
            "id": iid,
            "tabular": d.get("tabular", False),
            "series": series_chart,
            "ma12": ma12_chart,
            "periodos": periodos_chart,
            "unidad": d.get("unidad", ""),
            "chart_tipo": d.get("_chart_tipo"),
            "chart_titulo": d.get("_chart_titulo"),
        }
        # Datos YoY para empleo_imss
        if iid == "empleo_imss":
            indic_payload["imss_nac_yoy_periodos"] = d_ctx.get("_nac_yoy_periodos", [])
            indic_payload["imss_nac_yoy_valores"]  = d_ctx.get("_nac_yoy_valores", [])
            indic_payload["imss_sector_yoy"]       = d_ctx.get("_sector_yoy", {})
        # Para tabular con bar_horizontal, exponer labels/values derivados de filas
        if d.get("_chart_tipo") == "bar_horizontal":
            filas = d.get("filas") or []
            if iid == "export_entidad":
                indic_payload["bar_labels"] = [r.get("Entidad") for r in filas]
                indic_payload["bar_values"] = [r.get("Participación") for r in filas]
                indic_payload["bar_unit"] = "%"
            elif iid == "pib_estatal":
                try:
                    raw_pib = json.loads((ROOT / "data" / "pib_estatal.json").read_text(encoding="utf-8"))
                    all_pib = sorted(
                        [r for r in raw_pib.get("series", []) if r.get("Entidad") != "Estados Unidos Mexicanos"],
                        key=lambda r: r.get("Participacion") if r.get("Participacion") is not None else 0,
                        reverse=True
                    )
                except Exception:
                    all_pib = filas
                indic_payload["bar_labels"] = [r.get("Entidad") for r in all_pib]
                indic_payload["bar_values"] = [r.get("Participacion") for r in all_pib]
                indic_payload["bar_unit"] = "%"
            elif iid == "itaee_estatal":
                sort_key = d.get("_bar_sort_key") or "Var_anual"
                try:
                    raw_iid = json.loads((ROOT / "data" / "itaee_estatal.json").read_text(encoding="utf-8"))
                    all_series = sorted(raw_iid.get("series", []), key=lambda r: r.get(sort_key) if r.get(sort_key) is not None else -9999, reverse=True)
                except Exception:
                    all_series = filas
                indic_payload["bar_labels"] = [r.get("Entidad") for r in all_series]
                indic_payload["bar_values"] = [r.get(sort_key) for r in all_series]
                indic_payload["bar_unit"] = "%"
                indic_payload["bar_diverging"] = True
        # Para bar_grouped_horizontal (imai_estatal)
        if d.get("_chart_tipo") == "bar_grouped_horizontal" and iid == "imai_estatal":
            try:
                raw_imai = json.loads((ROOT / "data" / "imai_estatal.json").read_text(encoding="utf-8"))
                all_imai = sorted(raw_imai.get("series", []), key=lambda r: r.get("Indice_secundarias") if r.get("Indice_secundarias") is not None else 0, reverse=True)
                indic_payload["bar_labels"] = [r.get("Entidad") for r in all_imai]
                indic_payload["bar_datasets"] = [
                    {"label": "Índice secundarias", "values": [r.get("Indice_secundarias") for r in all_imai]},
                    {"label": "Índice manufacturas", "values": [r.get("Indice_manufacturas") for r in all_imai]},
                ]
            except Exception:
                pass
        # Para bar_grouped_horizontal (enoe_trimestral): bloque Total, absolutos en millones
        if d.get("_chart_tipo") == "bar_grouped_horizontal" and iid == "enoe_trimestral":
            try:
                raw_enoe = json.loads((ROOT / "data" / "enoe_trimestral.json").read_text(encoding="utf-8"))
                col_abs_act = d.get("_col_abs_act", "")
                col_abs_prev = d.get("_col_abs_prev", "")
                p_act = d.get("_p_act", "T_act")
                p_prev = d.get("_p_prev", "T_prev")
                # Tomar las primeras 7 filas (bloque Total)
                total_rows = [r for r in raw_enoe.get("series", [])[:7]]
                labels = [(r.get("Concepto") or "").strip() for r in total_rows]
                def _m(v):
                    return round(v / 1_000_000, 2) if v is not None else None
                indic_payload["bar_labels"] = labels
                indic_payload["bar_datasets"] = [
                    {"label": p_prev, "values": [_m(r.get(col_abs_prev)) for r in total_rows]},
                    {"label": p_act, "values": [_m(r.get(col_abs_act)) for r in total_rows]},
                ]
                indic_payload["bar_unit"] = "millones"
            except Exception:
                pass
        # grouped_series para bar_vertical y bar_grouped (indicadores no tabulares)
        if d.get("grouped_series"):
            indic_payload["grouped_series"] = d["grouped_series"]
        # Pasar drilldown si existe para que JS pueda renderizar paneles especiales
        if d_ctx.get("drilldown"):
            indic_payload["drilldown"] = d_ctx["drilldown"]
        # Pasar benchmark del indicador (banda Banxico, umbrales, etc.)
        if iid in benchmarks_cfg:
            indic_payload["benchmark"] = benchmarks_cfg[iid]
        # Pasar eventos macro relevantes (filtrar a la ventana del periodos del chart)
        periodos = periodos_chart
        if periodos and not d.get("tabular"):
            eventos_filtrados = []
            for ev in eventos_cfg:
                fecha = ev.get("fecha")
                # Convertir 'YYYY-MM' a periodo del indicador
                if fecha and "-" in fecha:
                    try:
                        y, m = fecha.split("-")
                        meses_lab = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
                        periodo_label = f"{meses_lab[int(m)-1]}-{y[-2:]}"
                        if periodo_label in periodos:
                            eventos_filtrados.append({**ev, "periodo": periodo_label, "indice": periodos.index(periodo_label)})
                    except Exception:
                        pass
            if eventos_filtrados:
                indic_payload["eventos_macro"] = eventos_filtrados
        page_data_det = {"view": "detail", "indicador": indic_payload}
        # Próxima publicación específica de este indicador (no la global)
        prox_indic = d.get("proximaPub") or {}
        prox_pub_local = (
            f"{d.get('_label_tabla') or d.get('nombre', iid)} · {prox_indic.get('fecha', '—')}"
            if prox_indic.get("fecha") and prox_indic.get("fecha") != "—"
            else cal_ctx["prox_pub"]
        )
        # Fecha larga para topbar v3
        meses_full = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                      "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        fecha_larga_v3 = f"{hoy.day} de {meses_full[hoy.month - 1]} de {hoy.year}"
        ctx = {
            "page_title": d.get("nombre", iid),
            "topbar_title": d.get("nombre", iid),
            "build_label": BUILD_LABEL,
            "build_chip": BUILD_CHIP,
            "build_fecha": fecha_larga_v3,
            "topbar_fecha": fecha_larga_v3,
            "ultima_pub": cal_ctx["ultima_pub"],
            "prox_pub": prox_pub_local,
            "asset_prefix": "../",
            "active_id": iid,
            "active_section": "indicadores",
            "nav_groups": [{"label": lbl, "items": [
                {"id": iid2, "label": lbl2, "href": href} for iid2, lbl2, href in items
            ]} for lbl, items in NAV_STRUCTURE],
            "d": d_ctx,
            "page_data_json": _json_for_script(page_data_det),
        }
        (SITE_DIR / "indicador" / f"{iid}.html").write_text(
            tmpl_det.render(**ctx), encoding="utf-8"
        )

    log.info("Build OK · %d indicadores · output: %s", len(indicadores), SITE_DIR)
    print(f"Build OK · {len(indicadores)} indicadores · output: {SITE_DIR}")


if __name__ == "__main__":
    main()
