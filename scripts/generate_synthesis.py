"""Genera data/home_synthesis.json automáticamente con Claude (Sonnet 4.6).

Lee los 32 indicadores y produce:
  - titulo: lectura macro fechada
  - parrafos: 3 párrafos de síntesis (precios, actividad, externo, empleo)
  - kpis_destacados: 4 KPI cards del hero

Requiere:
  - ANTHROPIC_API_KEY en .env
  - pip install anthropic --break-system-packages

Uso:
    python3 scripts/generate_synthesis.py
    python3 scripts/generate_synthesis.py --dry-run  # imprime sin escribir
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SYNTHESIS_PATH = DATA / "home_synthesis.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] synth: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("synth")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1500


def load_env() -> None:
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def collect_indicator_summary() -> str:
    """Construye un resumen compacto de todos los indicadores para enviar a Claude."""
    indicators = [
        ("inpc_mensual", "INPC anual", "INPC_Anual"),
        ("inpc_mensual", "INPC subyacente anual", "Subyacente_Anual"),
        ("inpp", "INPP sin petróleo anual", "Sin_petróleo_c_serv_Anual"),
        ("igae", "IGAE total var. mensual", "Total_Mensual"),
        ("igae", "IGAE total var. anual", "Total_Anual"),
        ("pib_trimestral", "PIB trimestral var. trim", "Trimestral"),
        ("pib_trimestral", "PIB anual desest", "Anual"),
        ("actividad_industrial", "Actividad industrial total", "Total"),
        ("balanza_comercial", "Saldo balanza MDD", "Saldo_total_MDD"),
        ("balanza_comercial", "Exportaciones anual", "Exportaciones_totales_Anual"),
        ("balanza_comercial", "Importaciones anual", "Importaciones_totales_Anual"),
        ("enoe_mensual", "Tasa desocupación", "Tasa_desocupacion_Total"),
        ("enoe_mensual", "Tasa participación", "Tasa_participacion_Total"),
        ("enoe_mensual", "Tasa informalidad", "Tasa_informalidad"),
        ("confianza_consumidor", "Confianza consumidor anual", "Anual"),
        ("emoe_ipm", "EMOE IPM anual", "Anual"),
        ("emoe_ice", "EMOE ICE anual", "Anual"),
        ("consumo_privado", "Consumo privado anual", "Total_Anual"),
        ("fbcf", "FBCF anual", "Total_Anual"),
        ("comercio_menudeo", "Comercio menudeo personal", "Personal_ocupado"),
        ("servicios", "EMS ingresos", "Ingresos_totales"),
        ("emim", "EMIM volumen producción", "Volumen_producción"),
        ("enec", "ENEC valor producción", "Valor_producción"),
        ("ind_ciclicos", "Coincidente", "Coincidente"),
        ("ind_ciclicos", "Adelantado", "Adelantado"),
    ]
    lines = []
    for iid, label, campo in indicators:
        f = DATA / f"{iid}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        rows = d.get("series", []) or []
        periodos = d.get("periodos", []) or []
        if not rows or not isinstance(rows[0], dict):
            continue
        valor = None
        periodo = None
        delta = None
        for i in range(len(rows) - 1, -1, -1):
            v = rows[i].get(campo)
            if v is not None:
                valor = v
                periodo = periodos[i] if i < len(periodos) else None
                if i > 0:
                    prev = rows[i - 1].get(campo)
                    if prev is not None:
                        delta = round(v - prev, 2)
                break
        if valor is None:
            continue
        delta_str = f" (Δ {delta:+.2f} vs previo)" if delta is not None else ""
        unidad = d.get("unidad", "")
        lines.append(f"- {label}: {valor:.2f} {unidad} en {periodo}{delta_str}")
    return "\n".join(lines)


PROMPT_TEMPLATE = """Eres analista macroeconómico de la Secretaría de Economía de México. Genera la lectura macro del tablero INEGI a partir de los datos vigentes que te paso.

Datos del periodo:
{datos}

Genera la lectura macro en formato JSON estricto con esta estructura exacta:

{{
  "titulo": "Lectura macro al {fecha_corta}",
  "parrafos": [
    "<párrafo 1: 3-4 oraciones cubriendo precios e inflación, conectando general/subyacente/INPP>",
    "<párrafo 2: 3-4 oraciones cubriendo actividad económica, IGAE, PIB, sectores industriales>",
    "<párrafo 3: 2-3 oraciones cubriendo sector externo (balanza, exportaciones), empleo (ENOE) y confianza>"
  ],
  "kpis_destacados": [
    {{"id": "inpc_mensual", "etiqueta": "Inflación anual", "valor": "X.XX%", "nota": "<contexto breve>"}},
    {{"id": "igae", "etiqueta": "<etiqueta>", "valor": "<valor>", "nota": "<nota>"}},
    {{"id": "balanza_comercial", "etiqueta": "<etiqueta>", "valor": "<valor>", "nota": "<nota>"}},
    {{"id": "enoe_mensual", "etiqueta": "<etiqueta>", "valor": "<valor>", "nota": "<nota>"}}
  ]
}}

Reglas:
- Estilo: directo, lenguaje claro y simple. Voz activa siempre. Evitar voz pasiva.
- Audiencia: altos mandos Secretaría de Economía. Asumir conocimiento experto.
- Cada afirmación respaldada por dato específico citado.
- Sin frases de cierre tipo "en conclusión".
- Sin guiones largos. Solo comas y puntos.
- Evitar adjetivos innecesarios.
- Mezclar español natural con términos técnicos.
- Para los KPIs, escoger los 4 movimientos más relevantes.

Devuelve SOLO el JSON, sin texto adicional ni código markdown."""


def call_claude(datos: str, fecha_corta: str) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError:
        log.error("Falta anthropic. Instala: pip install anthropic --break-system-packages")
        raise
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("Falta ANTHROPIC_API_KEY en .env o env vars")
        raise RuntimeError("API key faltante")
    client = Anthropic(api_key=api_key)
    prompt = PROMPT_TEMPLATE.format(datos=datos, fecha_corta=fecha_corta)
    log.info("Llamando %s con %d tokens en datos", MODEL, len(datos))
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    # Strip code fences si los hay
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


def _numeros(texto: str) -> list[float]:
    """Extrae números (tolerando coma de miles y signo) de un texto."""
    out = []
    for m in re.findall(r"-?\d[\d,]*\.?\d*", texto or ""):
        try:
            out.append(round(float(m.replace(",", "")), 2))
        except ValueError:
            continue
    return out


def _numero_en_fuente(valor: float, fuente: set[float]) -> bool:
    """True si 'valor' aparece en la fuente con tolerancia de redondeo
    (o coincide en magnitud, p. ej. saldo -1234 vs 1234)."""
    return any(abs(valor - f) <= 0.05 or abs(abs(valor) - abs(f)) <= 0.05 for f in fuente)


def validar_sintesis(resultado: dict, datos: str) -> list[str]:
    """Único guardrail antifabricación de los KPI hero. Verifica estructura y que
    cada número citado en kpis_destacados exista en los datos fuente (derivados de
    data/*.json). Devuelve lista de problemas; vacía = OK."""
    problemas = []
    if not isinstance(resultado.get("titulo"), str) or not resultado["titulo"].strip():
        problemas.append("titulo ausente o vacío")
    parrafos = resultado.get("parrafos")
    if not isinstance(parrafos, list) or not any(
        isinstance(p, str) and p.strip() for p in parrafos
    ):
        problemas.append("parrafos ausentes o vacíos")
    kpis = resultado.get("kpis_destacados")
    if not isinstance(kpis, list) or not kpis:
        problemas.append("kpis_destacados ausentes")
        return problemas
    fuente = set(_numeros(datos))
    for i, k in enumerate(kpis):
        if not isinstance(k, dict) or not k.get("etiqueta") or not k.get("valor"):
            problemas.append(f"kpi[{i}] incompleto")
            continue
        for n in _numeros(str(k.get("valor", ""))):
            if not _numero_en_fuente(n, fuente):
                problemas.append(
                    f"kpi[{i}] '{k.get('etiqueta')}' cita {n} que no existe en los "
                    "datos fuente (posible fabricación)"
                )
    return problemas


def _write_json_atomic(path: Path, obj) -> None:
    """Escritura atómica (tmp + rename)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fmt_fecha_corta(d: date) -> str:
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{d.day} de {meses[d.month - 1]}"


def fmt_ventana(d: date) -> str:
    """Construye 'Indicadores publicados entre <mes> y <mes> <año>'."""
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    prev_m = (d.month - 2) % 12
    return f"Indicadores publicados entre {meses[prev_m]} y {meses[d.month - 1]} {d.year}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Imprime sin escribir")
    args = p.parse_args(argv)

    load_env()
    datos = collect_indicator_summary()
    if not datos.strip():
        log.error("No se pudieron extraer datos de los indicadores")
        return 2

    hoy = date.today()
    fecha_corta = fmt_fecha_corta(hoy)
    log.info("Datos compilados (%d líneas), llamando Claude...", len(datos.splitlines()))
    try:
        resultado = call_claude(datos, fecha_corta)
    except Exception as e:
        log.error("Falla en llamada Claude: %s", e)
        return 1

    problemas = validar_sintesis(resultado, datos)
    if problemas:
        log.error("Síntesis RECHAZADA. NO se sobrescribe %s (se conserva la previa):",
                  SYNTHESIS_PATH.name)
        for p in problemas:
            log.error("  · %s", p)
        return 1

    # Estructura final con metadata
    out = {
        "_descripcion": "Síntesis macro generada automáticamente con Claude Sonnet. Revisar antes de publicar.",
        "_version": "3.0-auto",
        "ultima_actualizacion": hoy.isoformat(),
        "ventana_cubierta": fmt_ventana(hoy),
        "titulo": resultado.get("titulo", f"Lectura macro al {fecha_corta}"),
        "parrafos": resultado.get("parrafos", []),
        "kpis_destacados": resultado.get("kpis_destacados", []),
        "_fuente": "Claude Sonnet 4.6 sobre datos BIE-INEGI",
    }

    if args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    _write_json_atomic(SYNTHESIS_PATH, out)
    log.info("Síntesis escrita en %s", SYNTHESIS_PATH.relative_to(ROOT))
    log.info("Título: %s", out["titulo"])
    log.info("KPIs: %d destacados", len(out.get("kpis_destacados", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
