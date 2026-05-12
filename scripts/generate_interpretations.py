"""Genera data/interpretations.json con interpretaciones por indicador usando DeepSeek.

Estilo definitivo: replica el tono del documento "Seguimiento de coyuntura económica"
(referencia: config/estilo_interpretacion.md y config/glosario_traducido.json).
Audiencia: Subsecretaría de Economía, no académica.

Schema de salida por indicador (tipo "auto_v2"):
{
  "tipo": "auto_v2",
  "headline":   "1 a 2 frases, titular ejecutivo en lenguaje plano",
  "parrafos":   ["párr 1", "párr 2", "párr 3 opcional"],
  "diagnostico":"párrafo de cierre interpretativo (no resumen)",
  "mensaje":    "<headline + parrafos + diagnostico concatenados>",  # backward compat
  "generado_en":"YYYY-MM-DD",
  "basado_en":  "YYYY-MM-DD",
  "modelo":     "deepseek-chat"
}

Lógica de actualización:
  - Por defecto: solo regenera indicadores cuya última publicación en calendar.json
    es más reciente que el campo basado_en almacenado.
  - --force: regenera todos.
  - --id igae: regenera solo el indicador especificado.
  - --dry-run: imprime prompts sin llamar API ni escribir.

Requiere:
  - DEEPSEEK_API_KEY en .env
  - pip install openai --break-system-packages
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
ESTILO_PATH = CONFIG / "estilo_interpretacion.md"
GLOSARIO_PATH = CONFIG / "glosario_traducido.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] interp: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("interp")

DEFAULT_PROVIDER = os.environ.get("INTERP_PROVIDER", "deepseek")  # "deepseek" | "claude"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 1400
VERIFIER_MAX_TOKENS = 4000  # verifier reescribe draft completo + issues, necesita más espacio
COMUNICADO_MAX_CHARS = 1000

# Indicadores a ignorar.
SKIP_IDS = {"catalog", "igae_ioae_resumen"}


# ─────────────────────────────────────────────────────────────────────
# Carga de configuración y env
# ─────────────────────────────────────────────────────────────────────

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


def load_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def get_deepseek_client():
    try:
        from openai import OpenAI
    except ImportError:
        log.error("Falta openai. Instala: pip install openai --break-system-packages")
        raise
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        log.error("Falta DEEPSEEK_API_KEY en .env o env vars")
        raise RuntimeError("DEEPSEEK_API_KEY faltante")
    return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


def get_claude_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        log.error("Falta anthropic. Instala: pip install anthropic --break-system-packages")
        raise
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        log.error("Falta ANTHROPIC_API_KEY en .env o env vars")
        raise RuntimeError("ANTHROPIC_API_KEY faltante")
    return Anthropic(api_key=api_key)


def get_client(provider: str):
    if provider == "deepseek":
        return get_deepseek_client()
    if provider == "claude":
        return get_claude_client()
    raise ValueError(f"Proveedor desconocido: {provider!r}. Usa 'deepseek' o 'claude'.")


def default_model_for(provider: str) -> str:
    if provider == "deepseek":
        return DEEPSEEK_MODEL
    if provider == "claude":
        return CLAUDE_MODEL
    raise ValueError(f"Proveedor desconocido: {provider!r}")


# ─────────────────────────────────────────────────────────────────────
# Helpers de datos (preservados del script anterior)
# ─────────────────────────────────────────────────────────────────────

def evaluar_umbral(iid: str, ultima_fila: dict, thresholds: dict) -> str:
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


def extraer_tendencia(series: list[dict], periodos: list[str], n: int = 24) -> dict:
    if not series:
        return {"periodos": [], "filas": [], "ultimo_periodo": None}
    ultimas = series[-n:]
    ults_p = periodos[-n:] if periodos else []
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
    excluir_prefijos = ("Total_", "Periodo", "Mes")
    componentes = {}
    for k, v in ultima_fila.items():
        if v is None:
            continue
        if any(k.startswith(p) for p in excluir_prefijos):
            continue
        componentes[k] = round(v, 2) if isinstance(v, float) else v
    if not componentes:
        return ""
    items = list(componentes.items())[:8]
    return ", ".join(f"{k}={v}" for k, v in items)


def leer_comunicado(iid: str) -> str:
    ruta = CACHE_PRENSA / f"{iid}.txt"
    if not ruta.exists():
        return ""
    texto = ruta.read_text(encoding="utf-8").strip()
    if len(texto) > COMUNICADO_MAX_CHARS:
        texto = texto[:COMUNICADO_MAX_CHARS] + "..."
    return texto


def proxima_publicacion(iid: str, calendar: dict) -> str:
    cal_ind = calendar.get("indicadores", {}).get(iid, {})
    proximas = cal_ind.get("proximas_publicaciones", [])
    if proximas:
        return proximas[0].get("fecha", "")
    return ""


def ultima_publicacion_calendar(iid: str, calendar: dict) -> str:
    cal_ind = calendar.get("indicadores", {}).get(iid, {})
    ult = cal_ind.get("ultima_publicacion_ics", {})
    return ult.get("fecha", "")


def get_campo_principal(iid: str, ultima_fila: dict, thresholds: dict) -> tuple[str, float | None]:
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


# ─────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────

def _format_acronimo_relevante(iid: str, glosario: dict) -> str:
    """Devuelve la expansión + qué_mide del acrónimo del indicador, si está en glosario."""
    iid_upper = iid.upper()
    acronimos = glosario.get("acronimos", {})
    # Coincidencias directas o con prefijo del id
    for acr, defi in acronimos.items():
        if acr.upper() in iid_upper.split("_") or iid_upper.startswith(acr.upper()):
            return f"{acr}: {defi['expansion']}, {defi['que_mide']}."
    return ""


def build_system_message(estilo: str, glosario: dict) -> str:
    """System message global: estilo + reglas duras + glosario completo."""
    glosario_resumen = json.dumps(
        {
            "acronimos": {k: f"{v['expansion']}, {v['que_mide']}" for k, v in glosario.get("acronimos", {}).items()},
            "terminos_macro": {k: v["plano"] for k, v in glosario.get("terminos_macro", {}).items()},
            "conectores_recomendados": glosario.get("conectores_recomendados", []),
            "frases_a_evitar": glosario.get("frases_a_evitar", []),
        },
        ensure_ascii=False,
        indent=2,
    )
    return f"""Eres economista analista de coyuntura para la Subsecretaría de Economía de México. Tu trabajo es producir lecturas breves de indicadores económicos para la subsecretaria, quien tiene responsabilidad ejecutiva pero no formación académica formal en economía. Tu objetivo es que ella entienda qué muestran los datos, qué significan en términos prácticos y qué implican para el diagnóstico de la economía.

ESTILO OBLIGATORIO (calibrado contra documento de referencia interno):
{estilo}

GLOSARIO INTERNO (úsalo. Cuando aparezca un acrónimo o término técnico, traduce o expande siguiendo este glosario):
{glosario_resumen}

REGLAS DURAS DE FORMA:
- Prosa expositiva. Sin viñetas, sin headings dentro del texto, sin markdown.
- Voz activa. Sujetos económicos concretos.
- Acrónimo siempre con expansión y descripción funcional al primer uso.
- Cada dato cuantitativo va con su interpretación, nunca suelto.
- Sin símbolos crudos como σ, %YoY, p.p. Escribe "puntos porcentuales".
- Sin frases de cierre retórico. Sin metáforas. Sin adjetivos sin respaldo.
- Sin guiones largos. Solo comas, puntos y conectores naturales.

REGLAS DURAS DE FONDO (críticas, esto es para una Subsecretaría):

1. PROHIBIDO afirmar hechos históricos que no se puedan verificar contra los periodos provistos en el bloque "ÚLTIMOS N PERIODOS". Específicamente, NO uses construcciones como:
   - "primera vez desde [año o periodo no provisto]"
   - "peor lectura desde [año no provisto]"
   - "máximo / mínimo histórico"
   - "no ocurría desde [año no provisto]"
   - "desde la pandemia", "desde 2020", "desde 2008"
   Si quieres mencionar un antecedente, debe estar dentro de los periodos provistos. Si no lo está, omite la afirmación.

2. PROHIBIDO inventar datos. No inventes magnitudes, porcentajes, niveles o fechas que no estén en los datos provistos. Si no tienes un dato específico, redacta sin él.

3. PROHIBIDO recomendar política pública en el campo "diagnostico" ni en ningún otro. NO uses frases como:
   - "obliga a revisar las proyecciones"
   - "se debe considerar estímulos"
   - "es necesario implementar"
   - "el gobierno debería"
   - "se recomienda"
   El diagnóstico es lectura interpretativa de qué muestra el indicador. La toma de decisiones es competencia de la Subsecretaría, tú entregas insumo analítico.

4. AFIRMACIONES SOBRE CONTEXTO INTERNACIONAL (Fed, Banxico, EUA, peers LATAM, commodities) solo si la afirmación es estructural y no requiere cifras específicas que no tienes. Frases tipo "la desaceleración de la economía estadounidense" son aceptables. NO inventes cifras de PIB de EUA, tasa Fed, precio del Brent o cualquier serie externa.

5. SI EL INDICADOR ES NUEVO O LA SERIE TIENE POCOS PERIODOS (menos de 6), reduce la profundidad analítica. Mejor entregar 2 párrafos sólidos sin afirmaciones históricas que 3 párrafos con riesgo de error.
"""


def build_datos_resumen(iid: str, data: dict, thresholds: dict, calendar: dict, glosario: dict) -> str:
    """Bloque común que ven writer y verifier: datos, umbrales, comunicado.
    Garantiza que ambos modelos juzguen contra el mismo set de hechos."""
    periodos = data.get("periodos", [])
    series = data.get("series", [])
    tendencia = extraer_tendencia(series, periodos, n=24)
    ultima_fila = tendencia["filas"][-1] if tendencia["filas"] else {}
    umbral_str = evaluar_umbral(iid, ultima_fila, thresholds)
    componentes_str = extraer_componentes(ultima_fila)
    comunicado = leer_comunicado(iid)
    prox_pub = proxima_publicacion(iid, calendar)
    acronimo = _format_acronimo_relevante(iid, glosario)

    campo_ppal, valor_ppal = get_campo_principal(iid, ultima_fila, thresholds)
    dato_entrada = (
        f"{data.get('nombre', iid)} · {campo_ppal} = {valor_ppal} {data.get('unidad', '')} "
        f"({tendencia['ultimo_periodo']})"
        if valor_ppal is not None else data.get('nombre', iid)
    )

    primer_periodo = tendencia["periodos"][0] if tendencia["periodos"] else "(sin datos)"
    ultimo_periodo = tendencia["ultimo_periodo"] or "(sin datos)"

    bloque = f"""DATO DE ENTRADA: {dato_entrada}

INDICADOR: {data.get('nombre', iid)} ({iid})
UNIDAD: {data.get('unidad', '')}
FRECUENCIA: {data.get('frecuencia', '')}
ÚLTIMO PERIODO: {ultimo_periodo}
RANGO DE DATOS DISPONIBLES: de {primer_periodo} a {ultimo_periodo}.
RESTRICCIÓN: toda afirmación histórica que hagas (comparaciones, máximos, mínimos, antecedentes) debe estar respaldada por los periodos listados a continuación. NO uses referencias temporales fuera de este rango.
"""
    if acronimo:
        bloque += f"\nDEFINICIÓN PARA ESTE INDICADOR: {acronimo}\n"

    bloque += f"\nÚLTIMOS {len(tendencia['filas'])} PERIODOS (toda comparación histórica debe limitarse a este rango):\n"
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

    return bloque


TAREA_WRITER = """
TAREA: produce una interpretación del indicador con el estilo y reglas del system message. Devuelve EXACTAMENTE este JSON, sin comentarios, sin markdown, sin texto fuera del JSON:

{
  "headline":   "1 a 2 frases. Titular ejecutivo que la subsecretaria pueda leer y entender la idea principal sin más contexto. 25 a 50 palabras. SIN afirmaciones históricas fuera del rango provisto.",
  "parrafos": [
    "Párrafo 1 (60 a 120 palabras): identifica el indicador, explica brevemente qué mide, presenta el dato más reciente con su periodo y entrega la interpretación inmediata. Toda afirmación cuantitativa debe estar en los datos provistos.",
    "Párrafo 2 (60 a 120 palabras): conecta con periodos anteriores DENTRO del rango provisto, o con componentes del propio indicador. Explica la dinámica observada.",
    "Párrafo 3 OPCIONAL (60 a 120 palabras): contexto cualitativo nacional o internacional. Sólo afirmaciones estructurales (ej. 'desaceleración de la economía estadounidense'). NO inventes cifras de Fed, Brent, peers LATAM, ni de ninguna otra serie no provista. Si no puedes aportar contexto sin inventar, omite este párrafo."
  ],
  "diagnostico": "Párrafo de cierre (40 a 80 palabras). Lectura interpretativa de qué muestra el indicador para el diagnóstico general. PROHIBIDO recomendar política pública. PROHIBIDO usar 'obliga', 'se debe', 'es necesario', 'se recomienda'. Sólo lectura."
}

Si el rango de datos es corto o no tienes contexto que aportar sin inventar, devuelve 2 párrafos en lugar de 3. Más vale corto y exacto que largo y dudoso.
"""


def build_user_prompt(iid: str, data: dict, thresholds: dict, calendar: dict, glosario: dict) -> str:
    """Prompt completo para el writer."""
    return build_datos_resumen(iid, data, thresholds, calendar, glosario) + TAREA_WRITER


# ─────────────────────────────────────────────────────────────────────
# Llamada API
# ─────────────────────────────────────────────────────────────────────

def _parse_json_strict(text: str) -> dict:
    """Parsea JSON con limpieza de code fences y valida schema mínimo."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    parsed = json.loads(text)
    if not isinstance(parsed.get("headline"), str):
        raise ValueError("headline ausente o no string")
    if not isinstance(parsed.get("parrafos"), list) or not parsed["parrafos"]:
        raise ValueError("parrafos ausente o vacío")
    if not isinstance(parsed.get("diagnostico"), str):
        raise ValueError("diagnostico ausente")
    return parsed


def _call_deepseek_once(client, system_msg: str, user_prompt: str, model: str, max_tokens: int = MAX_TOKENS) -> str:
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.4,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _call_claude_once(client, system_msg: str, user_prompt: str, model: str, max_tokens: int = MAX_TOKENS) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.4,
        system=system_msg,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return resp.content[0].text


def call_llm(provider: str, client, system_msg: str, user_prompt: str, iid: str, model: str, max_tokens: int = MAX_TOKENS) -> dict:
    """Despacha al proveedor adecuado, parsea JSON y reintenta hasta 3 veces."""
    one_call = _call_deepseek_once if provider == "deepseek" else _call_claude_once
    for intento in range(3):
        try:
            text = one_call(client, system_msg, user_prompt, model, max_tokens)
            return _parse_json_strict(text)
        except json.JSONDecodeError as e:
            log.warning("[%s] JSON inválido en intento %d: %s", iid, intento + 1, e)
            if intento == 2:
                raise
        except Exception as e:
            log.warning("[%s] Error API intento %d: %s", iid, intento + 1, e)
            if intento == 2:
                raise
            time.sleep(2 ** intento)
    return {}


# ─────────────────────────────────────────────────────────────────────
# Verifier (writer + critic pattern)
# ─────────────────────────────────────────────────────────────────────

VERIFIER_SYSTEM = """Eres el verificador del tablero económico Panorama MX de la Subsecretaría de Economía. Tu trabajo es revisar una interpretación generada por otro modelo (writer) contra los datos provistos y contra las reglas del estilo institucional. La interpretación llegará a una subsecretaria con responsabilidad ejecutiva. Cualquier error factual o de estilo es riesgo reputacional.

REVISIÓN OBLIGATORIA en cuatro frentes:

1. PRECISIÓN FACTUAL: cada cifra (porcentaje, magnitud, fecha, periodo) mencionada en el draft debe estar respaldada por los datos provistos. Si el draft afirma "industrial cayó 1.3%", verifica que la cifra esté en los datos. Si afirma "diciembre de 2025 creció 2.3% anual", verifica que dic-25 efectivamente tenga ese valor.

2. ANTI-ALUCINACIÓN HISTÓRICA: rechaza cualquier afirmación temporal fuera del rango provisto. Frases como "primera vez desde 2021", "máximo histórico", "no ocurría desde la pandemia" deben eliminarse o reformularse si los datos no las respaldan literalmente. También rechaza afirmaciones como "segunda contracción en los últimos tres meses" si el conteo no cuadra con los periodos provistos.

3. AUSENCIA DE RECOMENDACIÓN DE POLÍTICA: el diagnóstico debe ser lectura interpretativa, NO recomendación. Detecta y reescribe frases como "obliga a revisar", "se debe considerar", "es necesario", "se recomienda", "el gobierno debería".

4. ESTILO Y GLOSARIO: acrónimos expandidos al primer uso. Sin símbolos crudos (σ, %YoY, p.p.). Sin frases prohibidas ("en conclusión", "en resumen", "cabe destacar"). Prosa expositiva sin viñetas.

PROCESO:
- Revisa el draft contra los datos provistos y las 4 reglas.
- Si no detectas issues: veredicto "pass", no incluyas draft_corregido.
- Si detectas uno o más issues: veredicto "fix", lista cada issue con campo (headline | parrafos[i] | diagnostico), tipo (factual | alucinacion | politica | estilo) y descripción específica. Además entrega un draft_corregido completo con los issues resueltos, conservando lo que sí estaba bien.

REGLAS DEL CORREGIDOR:
- No introduzcas cifras nuevas que no estén en los datos provistos.
- Mantén el estilo y longitud aproximada del draft original cuando reescribas.
- Si una afirmación es dudosa pero no puedes verificarla con los datos, suprímela.

Devuelve EXACTAMENTE este JSON, sin texto fuera:

{
  "veredicto": "pass" | "fix",
  "issues": [
    {"campo": "headline" | "parrafos[0]" | "parrafos[1]" | "parrafos[2]" | "diagnostico", "tipo": "factual" | "alucinacion" | "politica" | "estilo", "descripcion": "explicación breve del problema"}
  ],
  "draft_corregido": {
    "headline": "...",
    "parrafos": ["...", "...", "..."],
    "diagnostico": "..."
  }
}

Si veredicto es "pass", el campo "issues" debe ser un arreglo vacío y "draft_corregido" puede omitirse o ser un objeto vacío.
"""


def build_verifier_user_prompt(datos_resumen: str, draft: dict) -> str:
    """Pasa los datos provistos al verifier junto con el draft a revisar."""
    return f"""{datos_resumen}

══════════════════════════════════════════════════════════════════════
DRAFT GENERADO POR EL WRITER (a revisar):
══════════════════════════════════════════════════════════════════════

HEADLINE:
{draft.get('headline', '')}

PÁRRAFOS:
{chr(10).join(f"[{i}] " + p for i, p in enumerate(draft.get('parrafos', [])))}

DIAGNÓSTICO:
{draft.get('diagnostico', '')}

══════════════════════════════════════════════════════════════════════

Revisa el draft contra los datos provistos arriba y las 4 reglas del system. Devuelve el JSON de veredicto.
"""


def _parse_verifier_json(text: str) -> dict:
    """Parsea respuesta del verifier. Acepta draft_corregido ausente cuando pass."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    parsed = json.loads(text)
    if parsed.get("veredicto") not in ("pass", "fix"):
        raise ValueError("veredicto ausente o inválido")
    parsed.setdefault("issues", [])
    if parsed["veredicto"] == "fix":
        draft = parsed.get("draft_corregido")
        if not isinstance(draft, dict) or not draft.get("headline") or not draft.get("parrafos") or not draft.get("diagnostico"):
            raise ValueError("draft_corregido ausente o incompleto cuando veredicto=fix")
    return parsed


def call_verifier(provider: str, client, datos_resumen: str, draft: dict, iid: str, model: str) -> dict:
    """Llama al verifier con cap de tokens alto (reescribe draft completo). Reintentos hasta 2 veces."""
    one_call = _call_deepseek_once if provider == "deepseek" else _call_claude_once
    user_prompt = build_verifier_user_prompt(datos_resumen, draft)
    for intento in range(2):
        try:
            text = one_call(client, VERIFIER_SYSTEM, user_prompt, model, VERIFIER_MAX_TOKENS)
            return _parse_verifier_json(text)
        except json.JSONDecodeError as e:
            log.warning("[%s] Verifier JSON inválido intento %d: %s", iid, intento + 1, e)
            if intento == 1:
                raise
        except Exception as e:
            log.warning("[%s] Verifier error intento %d: %s", iid, intento + 1, e)
            if intento == 1:
                raise
            time.sleep(1)
    return {}


# ─────────────────────────────────────────────────────────────────────
# Orquestación
# ─────────────────────────────────────────────────────────────────────

def necesita_actualizar(iid: str, interps: dict, calendar: dict) -> bool:
    stored = interps.get(iid, {})
    basado_en = stored.get("basado_en", "")
    ult_pub = ultima_publicacion_calendar(iid, calendar)
    if not basado_en:
        return True
    if not ult_pub:
        return False
    try:
        return datetime.strptime(ult_pub, "%Y-%m-%d") > datetime.strptime(basado_en, "%Y-%m-%d")
    except ValueError:
        return True


def listar_indicadores() -> list[str]:
    ids = []
    for f in sorted(DATA.glob("*.json")):
        iid = f.stem
        if iid not in SKIP_IDS and not iid.startswith("home_") and not iid.startswith("comparativa"):
            ids.append(iid)
    return ids


def concat_mensaje(parsed: dict) -> str:
    """Concatena headline + parrafos + diagnostico para backward compat con templates viejos."""
    partes = []
    if parsed.get("headline"):
        partes.append(parsed["headline"].strip())
    for p in parsed.get("parrafos", []):
        if isinstance(p, str) and p.strip():
            partes.append(p.strip())
    if parsed.get("diagnostico"):
        partes.append(parsed["diagnostico"].strip())
    return "\n\n".join(partes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Regenerar todos sin importar fechas")
    p.add_argument("--id", dest="indicador_id", help="Regenerar solo este indicador")
    p.add_argument("--ids", dest="indicador_ids", help="Lista separada por comas: igae,inpc_mensual")
    p.add_argument("--dry-run", action="store_true", help="Imprime prompts sin llamar API ni escribir")
    p.add_argument("--provider", "--writer", dest="writer", choices=["deepseek", "claude"], default=DEFAULT_PROVIDER,
                   help=f"Writer (default: {DEFAULT_PROVIDER}). Alias: --provider")
    p.add_argument("--verifier", choices=["deepseek", "claude"], default=None,
                   help="Verifier (default: el provider opuesto al writer)")
    p.add_argument("--no-verify", action="store_true", help="Saltar verificación (riesgo)")
    p.add_argument("--model", default=None, help="Modelo del writer (default según provider)")
    p.add_argument("--verifier-model", default=None, help="Modelo del verifier (default según verifier provider)")
    args = p.parse_args(argv)

    writer_provider = args.writer
    writer_model = args.model or default_model_for(writer_provider)
    use_verify = not args.no_verify
    verifier_provider = args.verifier or ("claude" if writer_provider == "deepseek" else "deepseek")
    verifier_model = args.verifier_model or default_model_for(verifier_provider)

    log.info("Writer: %s · %s", writer_provider, writer_model)
    if use_verify:
        log.info("Verifier: %s · %s", verifier_provider, verifier_model)
    else:
        log.warning("Verificación DESACTIVADA con --no-verify")

    load_env()

    thresholds = load_json(CONFIG / "thresholds.json")
    calendar = load_json(CONFIG / "calendar.json")
    estilo = load_text(ESTILO_PATH)
    glosario = load_json(GLOSARIO_PATH)

    if not estilo:
        log.warning("Falta %s, prompt sin estilo explícito", ESTILO_PATH.relative_to(ROOT))
    if not glosario:
        log.warning("Falta %s, prompt sin glosario", GLOSARIO_PATH.relative_to(ROOT))

    system_msg = build_system_message(estilo, glosario)

    raw = load_json(INTERP_PATH)
    interps = {
        k: v for k, v in raw.items()
        if isinstance(v, dict) and "tipo" in v
    }

    hoy = date.today().isoformat()

    if args.indicador_id:
        ids = [args.indicador_id]
    elif args.indicador_ids:
        ids = [i.strip() for i in args.indicador_ids.split(",") if i.strip()]
    else:
        ids = listar_indicadores()

    if not args.force and not args.indicador_id and not args.indicador_ids:
        ids = [iid for iid in ids if necesita_actualizar(iid, interps, calendar)]
        log.info("%d indicadores con publicación nueva según calendario", len(ids))
    elif args.force:
        log.info("--force: regenerando los %d indicadores", len(ids))

    if not ids:
        log.info("Sin indicadores para actualizar. Usa --force para forzar.")
        return 0

    if not args.dry_run:
        writer_client = get_client(writer_provider)
        verifier_client = None
        if use_verify:
            verifier_client = writer_client if verifier_provider == writer_provider else get_client(verifier_provider)
    else:
        writer_client = None
        verifier_client = None

    actualizados = 0
    errores = 0
    revisiones_humanas = 0

    for iid in ids:
        data_path = DATA / f"{iid}.json"
        if not data_path.exists():
            log.warning("[%s] Archivo data no encontrado, saltando", iid)
            continue

        data = load_json(data_path)
        if not data.get("series"):
            log.warning("[%s] Sin series de datos, saltando", iid)
            continue

        datos_resumen = build_datos_resumen(iid, data, thresholds, calendar, glosario)
        user_prompt = datos_resumen + TAREA_WRITER

        if args.dry_run:
            print(f"\n{'='*70}")
            print(f"INDICADOR: {iid}")
            print(f"{'='*70}")
            print("--- WRITER SYSTEM ---")
            print(system_msg[:600] + "..." if len(system_msg) > 600 else system_msg)
            print("--- WRITER USER ---")
            print(user_prompt[:2000] + "..." if len(user_prompt) > 2000 else user_prompt)
            if use_verify:
                print("--- VERIFIER SYSTEM ---")
                print(VERIFIER_SYSTEM[:600] + "...")
            continue

        log.info("→ writer (%s): %s (%s)", writer_provider, iid, data.get("nombre", ""))
        try:
            draft = call_llm(writer_provider, writer_client, system_msg, user_prompt, iid, writer_model)
            if not draft:
                log.warning("[%s] Writer respuesta vacía", iid)
                errores += 1
                continue

            # ── Verifier ──
            verificacion_meta = None
            draft_publicado = draft
            draft_original = None
            revision_humana = False

            if use_verify:
                log.info("  ↳ verifier (%s) revisando...", verifier_provider)
                try:
                    verif = call_verifier(verifier_provider, verifier_client, datos_resumen, draft, iid, verifier_model)
                except Exception as ve:
                    log.error("[%s] Verifier falló: %s · publicando draft sin verificar y marcando revisión humana", iid, ve)
                    verif = {"veredicto": "error", "issues": [{"campo": "_meta", "tipo": "verifier_error", "descripcion": str(ve)}]}

                veredicto = verif.get("veredicto")
                issues = verif.get("issues", [])

                if veredicto == "pass":
                    log.info("  ✓ verifier: pass")
                    verificacion_meta = {
                        "veredicto": "pass",
                        "issues_encontrados": [],
                        "correccion_aplicada": False,
                        "verifier_provider": verifier_provider,
                        "verifier_model": verifier_model,
                    }
                elif veredicto == "fix":
                    log.warning("  ⚠ verifier: fix con %d issues", len(issues))
                    for iss in issues:
                        log.warning("    · [%s/%s] %s", iss.get("campo"), iss.get("tipo"), iss.get("descripcion"))
                    corregido = verif.get("draft_corregido", {})
                    if corregido and corregido.get("headline") and corregido.get("parrafos") and corregido.get("diagnostico"):
                        draft_original = draft
                        draft_publicado = {
                            "headline": corregido["headline"],
                            "parrafos": corregido["parrafos"],
                            "diagnostico": corregido["diagnostico"],
                        }
                        verificacion_meta = {
                            "veredicto": "fix",
                            "issues_encontrados": issues,
                            "correccion_aplicada": True,
                            "verifier_provider": verifier_provider,
                            "verifier_model": verifier_model,
                        }
                    else:
                        log.error("  ✗ verifier marcó fix pero draft_corregido inválido. Marcando revisión humana.")
                        revision_humana = True
                        verificacion_meta = {
                            "veredicto": "fix_sin_correccion",
                            "issues_encontrados": issues,
                            "correccion_aplicada": False,
                            "verifier_provider": verifier_provider,
                            "verifier_model": verifier_model,
                        }
                else:
                    log.error("  ✗ verifier en estado %s, marcando revisión humana", veredicto)
                    revision_humana = True
                    verificacion_meta = {
                        "veredicto": veredicto or "error",
                        "issues_encontrados": issues,
                        "correccion_aplicada": False,
                        "verifier_provider": verifier_provider,
                        "verifier_model": verifier_model,
                    }

            ult_pub = ultima_publicacion_calendar(iid, calendar)
            registro = {
                "tipo": "auto_v2",
                "headline": draft_publicado["headline"].strip(),
                "parrafos": [p.strip() for p in draft_publicado["parrafos"] if isinstance(p, str) and p.strip()],
                "diagnostico": draft_publicado["diagnostico"].strip(),
                "mensaje": concat_mensaje(draft_publicado),
                "generado_en": hoy,
                "basado_en": ult_pub or data.get("ultima_actualizacion", hoy),
                "writer_provider": writer_provider,
                "writer_modelo": writer_model,
                "provider": writer_provider,
                "modelo": writer_model,
            }
            if verificacion_meta is not None:
                registro["verificacion"] = verificacion_meta
            if draft_original is not None:
                registro["draft_original"] = draft_original
            if revision_humana:
                registro["revision_humana"] = True
                revisiones_humanas += 1

            interps[iid] = registro
            actualizados += 1

            badge = "✓" if (not use_verify) or (verificacion_meta and verificacion_meta.get("veredicto") == "pass") else ("⚠ corregido" if (verificacion_meta and verificacion_meta.get("correccion_aplicada")) else "⛔ revisión")
            head_short = registro["headline"][:90] + ("..." if len(registro["headline"]) > 90 else "")
            log.info("%s %s · %s", badge, iid, head_short)

        except Exception as e:
            log.error("[%s] Falla: %s", iid, e)
            errores += 1

        time.sleep(0.5)

    if not args.dry_run and actualizados > 0:
        INTERP_PATH.write_text(
            json.dumps(interps, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("=== %d interpretaciones escritas en %s ===", actualizados, INTERP_PATH.relative_to(ROOT))

    if errores:
        log.warning("%d errores durante la generación", errores)
    if revisiones_humanas:
        log.warning("%d indicadores requieren REVISIÓN HUMANA (verifier no pudo corregir automáticamente)", revisiones_humanas)

    return 0 if errores == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
