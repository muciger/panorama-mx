"""Genera data/interpretations.json con interpretaciones por indicador usando DeepSeek API.

Para cada indicador lee:
  - data/{iid}.json       → serie histórica, benchmarks, alertas
  - config/thresholds.json → umbrales de alerta (verde/amarillo/rojo)
  - config/calendar.json  → última publicación y próximas fechas
  - cache/notas_prensa/{iid}.txt → comunicado oficial INEGI (si existe)

Escribe data/interpretations.json. normalize.py ya tiene el hook para leerlo
y sobrescribir el campo `interp` de cada indicador.

Lógica de actualización:
  - Por defecto (--calendar): solo regenera indicadores cuya última publicación
    en calendar.json es más reciente que el campo `basado_en` almacenado.
  - --force: regenera todos sin importar fechas.
  - --id igae: regenera solo el indicador especificado.
  - --dry-run: imprime prompts y resultados sin escribir.

Requiere:
  - DEEPSEEK_API_KEY en .env
  - pip install openai --break-system-packages

Uso:
    python3 scripts/generate_interpretations.py              # solo desactualizados
    python3 scripts/generate_interpretations.py --force      # todos
    python3 scripts/generate_interpretations.py --id igae    # uno específico
    python3 scripts/generate_interpretations.py --dry-run    # sin escribir
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"
CACHE_PRENSA = ROOT / "cache" / "notas_prensa"
INTERP_PATH = DATA / "interpretations.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] interp: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("interp")

DEEPSEEK_MODEL = "deepseek-chat"
MAX_TOKENS = 400
COMUNICADO_MAX_CHARS = 800

# Indicadores a ignorar.
# catalog: archivo interno, no es página del tablero.
# igae_ioae_resumen: tabla pivot con columnas dinámicas, no es time series interpretable.
SKIP_IDS = {"catalog", "igae_ioae_resumen"}

INSTRUCCIONES_FIJAS = """
Escribe exactamente 3 oraciones de análisis para un directivo de política económica en México.

NO describes los datos, los interpretas. Cada oración responde exactamente una pregunta:
Oración 1 → ¿Qué señal macroeconómica emite el DATO DE ENTRADA? ¿Recuperación, deterioro estructural, volatilidad puntual o cambio de tendencia?
Oración 2 → ¿Qué lo explica causalmente? Identifica el factor o sector que lo está moviendo y por qué importa.
Oración 3 → ¿Qué implica para política económica o para el resto del año? Una implicación concreta, no genérica.

Reglas de estilo:
- Voz activa. Sin voz pasiva.
- Un argumento por oración, no un dato.
- Sin frases de cierre ("en conclusión", "en resumen", etc.).
- Sin adjetivos sin respaldo ("robusto", "sólido", "débil").
- Sin guiones largos. Solo comas y puntos.
- Español natural con términos técnicos precisos.
- No menciones la cifra exacta del DATO DE ENTRADA, ya aparece en los KPIs del tablero.

Devuelve ÚNICAMENTE este JSON, sin texto adicional ni markdown:
{"mensaje": "<oración 1> <oración 2> <oración 3>"}
"""


def load_env() -> None:
    envf = ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def get_deepseek_client():
    try:
        from openai import OpenAI
    except ImportError:
        log.error("Falta openai. Instala: pip install openai --break-system-packages")
        raise
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        log.error("Falta DEEPSEEK_API_KEY en .env o env vars")
        raise RuntimeError("API key faltante")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def evaluar_umbral(iid: str, ultima_fila: dict, thresholds: dict) -> str:
    """Devuelve descripción de posición vs umbral. Vacío si no hay threshold."""
    iid_thresh = thresholds.get("thresholds", {}).get(iid, {})
    if not iid_thresh:
        return ""
    partes = []
    for campo, regla in iid_thresh.items():
        valor = ultima_fila.get(campo)
        if valor is None:
            continue
        tipo = regla.get("tipo")
        if tipo == "max":
            verde = regla.get("verde_max")
            amarillo = regla.get("amarillo_max")
            if valor < verde:
                estado = "zona verde"
            elif valor < amarillo:
                estado = f"zona amarilla ({regla.get('mensaje_amarillo', '')})"
            else:
                estado = f"zona roja ({regla.get('mensaje_rojo', '')})"
            partes.append(f"{campo}={valor:.2f}, umbral verde <{verde}, {estado}")
        elif tipo == "min":
            verde = regla.get("verde_min")
            amarillo = regla.get("amarillo_min")
            if valor >= verde:
                estado = "zona verde"
            elif valor >= amarillo:
                estado = f"zona amarilla ({regla.get('mensaje_amarillo', '')})"
            else:
                estado = f"zona roja ({regla.get('mensaje_rojo', '')})"
            partes.append(f"{campo}={valor:.2f}, umbral verde >={verde}, {estado}")
    return "; ".join(partes)


def extraer_tendencia(series: list[dict], periodos: list[str], n: int = 6) -> dict:
    """Extrae los últimos n periodos con todos sus valores no-nulos."""
    if not series:
        return {"periodos": [], "filas": [], "ultimo_periodo": None}
    ultimas = series[-n:]
    ults_p = periodos[-n:] if periodos else []
    # Limpiar None de los valores de las filas para el prompt
    filas_limpias = []
    for fila in ultimas:
        limpia = {k: round(v, 3) if isinstance(v, float) else v
                  for k, v in fila.items()
                  if v is not None and k != "Mes"}
        filas_limpias.append(limpia)
    return {
        "periodos": ults_p,
        "filas": filas_limpias,
        "ultimo_periodo": ults_p[-1] if ults_p else None,
    }


def extraer_componentes(ultima_fila: dict) -> str:
    """Extrae columnas de desglose sectorial o por componente para el prompt."""
    excluir_prefijos = ("Total_", "Periodo", "Mes")
    excluir_sufijos = ("_Mensual",)  # para indicadores con muchas columnas, priorizar anuales
    componentes = {}
    for k, v in ultima_fila.items():
        if v is None:
            continue
        if any(k.startswith(p) for p in excluir_prefijos):
            continue
        componentes[k] = round(v, 2) if isinstance(v, float) else v
    if not componentes:
        return ""
    # Limitar a 8 componentes para no exceder tokens
    items = list(componentes.items())[:8]
    return ", ".join(f"{k}={v}" for k, v in items)


def leer_comunicado(iid: str) -> str:
    """Lee el comunicado oficial INEGI si existe. Trunca a COMUNICADO_MAX_CHARS."""
    ruta = CACHE_PRENSA / f"{iid}.txt"
    if not ruta.exists():
        return ""
    texto = ruta.read_text(encoding="utf-8").strip()
    if len(texto) > COMUNICADO_MAX_CHARS:
        texto = texto[:COMUNICADO_MAX_CHARS] + "..."
    return texto


def proxima_publicacion(iid: str, calendar: dict) -> str:
    """Devuelve la fecha de la próxima publicación del indicador."""
    cal_ind = calendar.get("indicadores", {}).get(iid, {})
    proximas = cal_ind.get("proximas_publicaciones", [])
    if proximas:
        return proximas[0].get("fecha", "")
    return ""


def ultima_publicacion_calendar(iid: str, calendar: dict) -> str:
    """Devuelve la fecha de la última publicación según el calendario ICS."""
    cal_ind = calendar.get("indicadores", {}).get(iid, {})
    ult = cal_ind.get("ultima_publicacion_ics", {})
    return ult.get("fecha", "")


def get_campo_principal(iid: str, ultima_fila: dict, thresholds: dict) -> tuple[str, float | None]:
    """Devuelve (nombre_campo, valor) del indicador principal para el DATO DE ENTRADA.

    Prioridad:
    1. Primer campo con threshold definido para ese indicador.
    2. Campo Total_Anual si existe.
    3. Primer campo que termine en _Anual.
    4. Primer campo no-Periodo/Mes con valor numérico.
    """
    def _num(v) -> float | None:
        if isinstance(v, (int, float)) and v is not True and v is not False:
            return round(float(v), 3)
        return None

    iid_thresh = thresholds.get("thresholds", {}).get(iid, {})
    for campo in iid_thresh:
        v = _num(ultima_fila.get(campo))
        if v is not None:
            return campo, v

    for candidate in ["Total_Anual", "Anual"]:
        v = _num(ultima_fila.get(candidate))
        if v is not None:
            return candidate, v

    for k, v in ultima_fila.items():
        if k in ("Periodo", "Mes"):
            continue
        if k.endswith("_Anual"):
            n = _num(v)
            if n is not None:
                return k, n

    for k, v in ultima_fila.items():
        if k not in ("Periodo", "Mes"):
            n = _num(v)
            if n is not None:
                return k, n

    return "valor", None


def build_prompt(iid: str, data: dict, thresholds: dict, calendar: dict) -> str:
    periodos = data.get("periodos", [])
    series = data.get("series", [])
    tendencia = extraer_tendencia(series, periodos, n=6)
    ultima_fila = tendencia["filas"][-1] if tendencia["filas"] else {}
    umbral_str = evaluar_umbral(iid, ultima_fila, thresholds)
    componentes_str = extraer_componentes(ultima_fila)
    comunicado = leer_comunicado(iid)
    prox_pub = proxima_publicacion(iid, calendar)

    campo_ppal, valor_ppal = get_campo_principal(iid, ultima_fila, thresholds)
    dato_entrada = (
        f"{data.get('nombre', iid)} · {campo_ppal} = {valor_ppal} {data.get('unidad', '')} "
        f"({tendencia['ultimo_periodo']})"
        if valor_ppal is not None else data.get('nombre', iid)
    )

    bloque = f"""DATO DE ENTRADA: {dato_entrada}

INDICADOR: {data.get('nombre', iid)} ({iid})
UNIDAD: {data.get('unidad', '')}
FRECUENCIA: {data.get('frecuencia', '')}
ÚLTIMO PERIODO: {tendencia['ultimo_periodo']}

ÚLTIMOS {len(tendencia['filas'])} PERIODOS:
"""
    for p, fila in zip(tendencia["periodos"], tendencia["filas"]):
        bloque += f"  {p}: {json.dumps(fila, ensure_ascii=False)}\n"

    if umbral_str:
        bloque += f"\nPOSICIÓN VS UMBRAL: {umbral_str}\n"

    if componentes_str:
        bloque += f"\nCOMPONENTES CLAVE: {componentes_str}\n"

    if prox_pub:
        bloque += f"\nPRÓXIMA PUBLICACIÓN: {prox_pub}\n"

    if comunicado:
        bloque += f"\nCOMUNICADO OFICIAL INEGI (extracto):\n{comunicado}\n"

    bloque += INSTRUCCIONES_FIJAS
    return bloque


def call_deepseek(client, prompt: str, iid: str) -> str:
    """Llama a DeepSeek y devuelve el campo 'mensaje'. Reintentos en error."""
    for intento in range(3):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                max_tokens=MAX_TOKENS,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres economista senior con 15 años en la Secretaría de Economía de México. "
                            "Tu trabajo es interpretar datos macroeconómicos para directivos que toman "
                            "decisiones de política. No describes lo que dicen los números, diagnosticas "
                            "qué está pasando en la economía, por qué, y qué implica. "
                            "Usas juicio analítico, no paráfrasis estadística."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            text = resp.choices[0].message.content.strip()
            # Limpiar code fences si los hay
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()
            parsed = json.loads(text)
            return parsed.get("mensaje", "")
        except json.JSONDecodeError as e:
            log.warning("[%s] JSON inválido en intento %d: %s", iid, intento + 1, e)
            if intento == 2:
                raise
        except Exception as e:
            log.warning("[%s] Error API intento %d: %s", iid, intento + 1, e)
            if intento == 2:
                raise
            time.sleep(2 ** intento)
    return ""


def necesita_actualizar(iid: str, interps: dict, calendar: dict) -> bool:
    """True si la interpretación almacenada es anterior a la última publicación del calendario."""
    stored = interps.get(iid, {})
    basado_en = stored.get("basado_en", "")
    ult_pub = ultima_publicacion_calendar(iid, calendar)
    if not basado_en:
        return True  # nunca generado
    if not ult_pub:
        return False  # sin fecha en calendario, no regenerar
    try:
        return datetime.strptime(ult_pub, "%Y-%m-%d") > datetime.strptime(basado_en, "%Y-%m-%d")
    except ValueError:
        return True


def listar_indicadores() -> list[str]:
    """Devuelve todos los IDs de indicadores disponibles en data/."""
    ids = []
    for f in sorted(DATA.glob("*.json")):
        iid = f.stem
        if iid not in SKIP_IDS and not iid.startswith("home_") and not iid.startswith("comparativa"):
            ids.append(iid)
    return ids


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Regenerar todos sin importar fechas")
    p.add_argument("--id", dest="indicador_id", help="Regenerar solo este indicador")
    p.add_argument("--ids", dest="indicador_ids", help="Regenerar lista separada por comas: igae,inpc_mensual")
    p.add_argument("--dry-run", action="store_true", help="Imprime prompts sin llamar API ni escribir")
    p.add_argument("--calendar", action="store_true", help="Solo indicadores con nueva publicación (default)")
    args = p.parse_args(argv)

    load_env()

    thresholds = load_json(CONFIG / "thresholds.json")
    calendar = load_json(CONFIG / "calendar.json")

    # Cargar interpretaciones existentes. Ignorar estructura legacy
    # {"_descripcion":..., "interpretaciones": {}} — solo conservar keys que
    # sean IDs de indicadores (dicts con campo "tipo").
    raw = load_json(INTERP_PATH)
    interps = {
        k: v for k, v in raw.items()
        if isinstance(v, dict) and "tipo" in v
    }

    hoy = date.today().isoformat()

    # Determinar qué indicadores procesar
    if args.indicador_id:
        ids = [args.indicador_id]
    elif args.indicador_ids:
        ids = [i.strip() for i in args.indicador_ids.split(",") if i.strip()]
    else:
        ids = listar_indicadores()

    if not args.force and not args.indicador_id and not args.indicador_ids:
        # Modo calendario: solo los que tienen publicación nueva
        ids = [iid for iid in ids if necesita_actualizar(iid, interps, calendar)]
        log.info("%d indicadores con publicación nueva según calendario", len(ids))
    elif args.force:
        log.info("--force: regenerando los %d indicadores", len(ids))

    if not ids:
        log.info("Sin indicadores para actualizar. Usa --force para forzar.")
        return 0

    if not args.dry_run:
        client = get_deepseek_client()
    else:
        client = None

    actualizados = 0
    errores = 0

    for iid in ids:
        data_path = DATA / f"{iid}.json"
        if not data_path.exists():
            log.warning("[%s] Archivo data no encontrado, saltando", iid)
            continue

        data = load_json(data_path)
        if not data.get("series"):
            log.warning("[%s] Sin series de datos, saltando", iid)
            continue

        prompt = build_prompt(iid, data, thresholds, calendar)

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"INDICADOR: {iid}")
            print(f"{'='*60}")
            print(prompt)
            continue

        log.info("→ generando interpretación: %s (%s)", iid, data.get("nombre", ""))
        try:
            mensaje = call_deepseek(client, prompt, iid)
            if not mensaje:
                log.warning("[%s] Respuesta vacía", iid)
                errores += 1
                continue

            ult_pub = ultima_publicacion_calendar(iid, calendar)
            interps[iid] = {
                "tipo": "auto",
                "mensaje": mensaje,
                "generado_en": hoy,
                "basado_en": ult_pub or data.get("ultima_actualizacion", hoy),
                "modelo": DEEPSEEK_MODEL,
            }
            actualizados += 1
            log.info("✓ %s: %s", iid, mensaje[:80] + "..." if len(mensaje) > 80 else mensaje)

        except Exception as e:
            log.error("[%s] Falla: %s", iid, e)
            errores += 1

        # Pausa breve entre llamadas para no saturar la API
        time.sleep(0.5)

    if not args.dry_run and actualizados > 0:
        INTERP_PATH.write_text(
            json.dumps(interps, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("=== %d interpretaciones escritas en %s ===", actualizados, INTERP_PATH.relative_to(ROOT))

    if errores:
        log.warning("%d errores durante la generación", errores)

    return 0 if errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
