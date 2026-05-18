"""Ingest desde comunicados RAIAVL y RAIAVP (archivos MD en comunicados_inegi/).

INEGI publica mensualmente:
  - RAIAVL: Registro Administrativo Industria Automotriz Vehículos Ligeros
  - RAIAVP: Registro Administrativo Industria Automotriz Vehículos Pesados

Cada boletín incluye headline cards con variación % anual de:
  - Ligeros: Ventas, Producción, Exportación
  - Pesados:  Ventas_Menudeo, Ventas_Mayoreo, Producción, Exportación

Los PDFs se pueden descargar automáticamente desde el API de sala de prensa del INEGI
(ver --fetch) o manualmente, y se convierten a MD con pymupdf4llm, pdfminer o pdftotext.
Este script parsea los MDs y hace upsert en data/autos_ligeros.json y
data/autos_pesados.json, preservando toda la serie histórica existente.

Flujo normal:
  1. Escanea COMUNICADOS_DIR (../../comunicados_inegi/) buscando MDs RAIAVL/RAIAVP
  2. Para cada MD encontrado: extrae periodo + variaciones % de los headline cards
  3. Hace upsert en data/{indicador}.json (inserta si no existe, actualiza si existe)
  4. Actualiza metadata: ultima_actualizacion, nota_ingest

Flujo --fetch:
  1. Consulta la API de sala de prensa del INEGI para obtener el último idNoticia
  2. Descarga el PDF más reciente de cada indicador a comunicados_inegi/
  3. Convierte a MD y procesa normalmente

Convención de nombres en comunicados_inegi/:
  autos_ligeros_rm_raiavl{YYYY}_{MM}.md   (publicación aprox. día 9 del mes)
  autos_pesados_rm_riavp{YYYY}_{MM}.md    (publicación aprox. día 10 del mes)

Uso:
    python3 scripts/ingest_amia.py             # procesa todos los MDs disponibles
    python3 scripts/ingest_amia.py --fetch     # descarga PDFs más recientes e ingesta
    python3 scripts/ingest_amia.py --fetch --dry-run  # descarga y reporta sin escribir
    python3 scripts/ingest_amia.py --dry-run   # reporta cambios sin escribir
    python3 scripts/ingest_amia.py --pdf ruta/boletin.pdf  # convierte y parsea un PDF
    python3 scripts/ingest_amia.py --check     # lista MDs disponibles y estado del JSON

APIs del INEGI utilizadas (sin autenticación, públicas):
  GET  /app/api/saladeprensa/api/saladeprensa/ComObtenerCalendarioPubPorProyecto/{id}/1/0
  POST /app/api/saladeprensa/api/saladeprensa/ObtenerInfoNoticia/v3
  GET  https://www.inegi.org.mx/contenidos{urlPdf}
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

try:
    import urllib.request as _urllib_req
    import urllib.parse as _urllib_parse
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

ROOT = Path(__file__).resolve().parent.parent
COMUNICADOS_DIR = ROOT.parent / "comunicados_inegi"

# API sala de prensa del INEGI (pública, sin token)
INEGI_BASE = "https://www.inegi.org.mx"
SALADEPRENSA_API = f"{INEGI_BASE}/app/api/saladeprensa/api/saladeprensa"

# IDs de proyecto en el API de sala de prensa para cada indicador
# Verificados el 2026-05-05 contra la página datosprimarios del INEGI
INEGI_PROYECTO_IDS = {
    "autos_ligeros": 340,  # RAIAVL: Reporte completo (Ventas + Producción + Exportación)
    "autos_pesados": 462,  # RAIAVP: Reporte completo (Ventas Menudeo/Mayoreo + Prod + Export)
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] amia: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("amia")

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MESES_ABR = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

# Columnas esperadas por indicador (en orden de aparición en el boletín)
COLUMNAS = {
    "autos_ligeros": ["Ventas", "Producción", "Exportación"],
    "autos_pesados": ["Ventas_Menudeo", "Ventas_Mayoreo", "Producción", "Exportación"],
}


# ── Parser ──────────────────────────────────────────────────────────────────


def detect_indicator(text: str) -> Optional[str]:
    """Identifica el indicador a partir del header del MD."""
    upper = text[:800].upper()
    if "VEHÍCULOS LIGEROS" in upper or "VEHICULOS LIGEROS" in upper or "RAIAVL" in upper:
        return "autos_ligeros"
    if "VEHÍCULOS PESADOS" in upper or "VEHICULOS PESADOS" in upper or "RAIAVP" in upper:
        return "autos_pesados"
    return None


def extract_periodo(text: str) -> Optional[str]:
    """
    Extrae el periodo reportado del encabezado del boletín.
    El encabezado repite el mes/año como 'mes YYYY' (ej. 'marzo 2026').
    Retorna formato 'mmm-YY' (ej. 'mar-26').
    """
    pattern = (
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto"
        r"|septiembre|octubre|noviembre|diciembre)\s+(\d{4})"
    )
    m = re.search(pattern, text[:600], re.IGNORECASE)
    if not m:
        return None
    mes_num = MESES_ES[m.group(1).lower()]
    return f"{MESES_ABR[mes_num]}-{m.group(2)[2:]}"


def extract_pct_cards(text: str, n_expected: int) -> list[float]:
    """
    Extrae las n_expected variaciones % anuales de los headline cards del boletín.

    Los cards tienen estructura:
      ### NN NNN
      **unidades
      ### [▲▼]
      ### [- ]N.N %          ← ligeros (positivo sin signo explícito)
      ### -
      ### NN.N %             ← pesados (negativo: '-' en línea separada)

    Estrategia: divide el header en segmentos por ▲ y ▼, y en cada segmento
    busca el primer número con formato 'N.N %'. El signo lo da el símbolo ▼ o la
    presencia de '- ' antes del número en las siguientes líneas.
    """
    # Tomar solo la sección de headline (antes del primer párrafo narrativo)
    end_match = re.search(r"\nSe (produjeron|vendieron|produj|comercializ)", text)
    header = text[: end_match.start() if end_match else 3000]

    values: list[float] = []
    segments = re.split(r"([▲▼])", header)

    for i, seg in enumerate(segments):
        if seg not in ("▲", "▼"):
            continue
        direction = 1 if seg == "▲" else -1
        rest = segments[i + 1] if i + 1 < len(segments) else ""

        # ¿Hay un '-' solitario en las primeras líneas del segmento?
        has_explicit_neg = bool(
            re.search(r"(?:^|\n)\s*#+\s*-\s*(?:\n|$)", rest[:400])
        )

        # Extrae el primer 'N.N %' en el segmento
        pct_m = re.search(r"(\d+[\.,]\d+)\s*%", rest[:400])
        if not pct_m:
            continue

        val = float(pct_m.group(1).replace(",", "."))
        if direction == -1 or has_explicit_neg:
            val = -val

        values.append(round(val, 1))
        if len(values) == n_expected:
            break

    return values


def parse_md(path: Path) -> Optional[dict]:
    """
    Parsea un MD de RAIAVL o RAIAVP.
    Retorna dict con keys: indicador, periodo, datos (dict columna→valor).
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    indicador = detect_indicator(text)
    if not indicador:
        log.warning("%s: no se reconoce como RAIAVL ni RAIAVP", path.name)
        return None

    periodo = extract_periodo(text)
    if not periodo:
        log.warning("%s: no se encontró periodo en el encabezado", path.name)
        return None

    cols = COLUMNAS[indicador]
    vals = extract_pct_cards(text, len(cols))

    if len(vals) != len(cols):
        log.error(
            "%s: se esperaban %d valores, se extrajeron %d → %s",
            path.name, len(cols), len(vals), vals,
        )
        return None

    datos = dict(zip(cols, vals))
    log.info("%s → %s %s %s", path.name, indicador, periodo, datos)
    return {"indicador": indicador, "periodo": periodo, "datos": datos, "fuente_md": path.name}


# ── Upsert JSON ──────────────────────────────────────────────────────────────


def _write_json_atomic(path: Path, obj: dict) -> None:
    """Escritura atómica (tmp + rename): preserva la serie histórica si el
    proceso muere a mitad de escritura."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def upsert_json(indicador: str, periodo: str, datos: dict, fuente_md: str, dry_run: bool) -> bool:
    """
    Actualiza data/{indicador}.json con el periodo nuevo o revisado.
    Preserva toda la serie existente. Retorna True si hubo cambio.
    """
    jpath = ROOT / "data" / f"{indicador}.json"
    if not jpath.exists():
        log.error("data/%s.json no existe", indicador)
        return False

    d = json.loads(jpath.read_text(encoding="utf-8"))
    series: list[dict] = d.get("series", [])
    cols = COLUMNAS[indicador]
    mes_key = "Mes"

    # Busca si el periodo ya existe
    existing_idx = next(
        (i for i, row in enumerate(series) if row.get(mes_key) == periodo), None
    )
    new_row = {mes_key: periodo, **datos}

    if existing_idx is not None:
        old = series[existing_idx]
        if all(old.get(c) == datos[c] for c in cols):
            log.info("%s %s: sin cambios", indicador, periodo)
            return False
        log.info("%s %s: actualiza %s → %s", indicador, periodo, old, new_row)
        if not dry_run:
            series[existing_idx] = new_row
    else:
        log.info("%s %s: inserta %s", indicador, periodo, new_row)
        if not dry_run:
            # Inserta manteniendo orden cronológico (el más reciente al final)
            series.append(new_row)

    if not dry_run:
        # Actualiza periodos (lista de strings para el selector)
        periodos = [row[mes_key] for row in series]
        d["series"] = series
        d["periodos"] = periodos
        d["ultima_actualizacion"] = date.today().isoformat()
        d["nota_ingest"] = (
            f"Actualizado desde comunicado INEGI {fuente_md}. "
            "Variaciones % anuales extraídas del headline del boletín RAIAVL/RAIAVP."
        )
        _write_json_atomic(jpath, d)
        log.info("data/%s.json escrito", indicador)

    return True


# ── Descarga automática desde INEGI sala de prensa ───────────────────────────


def _http_get_json(url: str) -> object:
    """GET simple que retorna JSON. Usa urllib (stdlib, sin dependencias extra)."""
    req = _urllib_req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with _urllib_req.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, data: dict) -> object:
    """POST form-urlencoded que retorna JSON."""
    body = _urllib_parse.urlencode(data).encode("utf-8")
    req = _urllib_req.Request(
        url, data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with _urllib_req.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_latest_noticia_id(proyecto_id: int) -> Optional[str]:
    """
    Consulta ComObtenerCalendarioPubPorProyecto y retorna el idNoticia más reciente.
    """
    url = f"{SALADEPRENSA_API}/ComObtenerCalendarioPubPorProyecto/{proyecto_id}/1/0"
    try:
        data = _http_get_json(url)
        if data and isinstance(data, list):
            return str(data[0]["idNoticia"])
    except Exception as exc:
        log.error("Error consultando calendario INEGI (id=%s): %s", proyecto_id, exc)
    return None


def get_pdf_url(noticia_id: str) -> Optional[str]:
    """
    Consulta ObtenerInfoNoticia/v3 y retorna la URL completa del PDF del boletín.
    """
    url = f"{SALADEPRENSA_API}/ObtenerInfoNoticia/v3"
    try:
        data = _http_post_json(url, {"acronimo": "", "idNoticia": noticia_id, "ingles": "0"})
        if data and isinstance(data, list):
            url_pdf = data[0].get("urlPdf", "")
            if url_pdf:
                return f"{INEGI_BASE}/contenidos{url_pdf}"
    except Exception as exc:
        log.error("Error consultando noticia %s: %s", noticia_id, exc)
    return None


def download_pdf(url: str, out_dir: Path) -> Optional[Path]:
    """
    Descarga un PDF del INEGI a out_dir.
    Si el archivo ya existe, lo retorna sin volver a descargarlo.
    Retorna la ruta del archivo o None si falla.
    """
    filename = url.split("/")[-1]
    out_path = out_dir / filename
    if out_path.exists():
        log.info("PDF ya existe localmente: %s", filename)
        return out_path
    try:
        req = _urllib_req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _urllib_req.urlopen(req, timeout=60) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                log.error("URL no retornó PDF (Content-Type=%s): %s", content_type, url)
                return None
            raw = resp.read()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        log.info("PDF descargado: %s (%.1f KB)", filename, len(raw) / 1024)
        return out_path
    except Exception as exc:
        log.error("Error descargando %s: %s", url, exc)
        return None


def fetch_latest_pdf(indicador: str) -> Optional[Path]:
    """
    Descarga el boletín más reciente del INEGI para autos_ligeros o autos_pesados.
    Retorna la ruta del PDF descargado, o None si no se pudo obtener.
    """
    proyecto_id = INEGI_PROYECTO_IDS.get(indicador)
    if not proyecto_id:
        log.error("No se conoce proyecto_id para indicador '%s'", indicador)
        return None

    noticia_id = get_latest_noticia_id(proyecto_id)
    if not noticia_id:
        log.error("%s: no se obtuvo idNoticia del API de sala de prensa", indicador)
        return None

    pdf_url = get_pdf_url(noticia_id)
    if not pdf_url:
        log.error("%s: no se obtuvo urlPdf para noticia %s", indicador, noticia_id)
        return None

    log.info("%s: noticia=%s, url=%s", indicador, noticia_id, pdf_url)
    return download_pdf(pdf_url, COMUNICADOS_DIR)


# ── PDF → MD ─────────────────────────────────────────────────────────────────


def pdf_to_md(pdf_path: Path, out_dir: Path) -> Optional[Path]:
    """
    Convierte un PDF a MD usando pdfminer o pymupdf4llm si están disponibles.
    Guarda el resultado en out_dir con el mismo nombre base + .md
    Retorna la ruta del MD o None si falla.
    """
    stem = pdf_path.stem
    out_path = out_dir / f"{stem}.md"

    # Intento 1: pymupdf4llm (más fiel para tablas)
    try:
        import pymupdf4llm  # type: ignore
        md_text = pymupdf4llm.to_markdown(str(pdf_path))
        out_path.write_text(md_text, encoding="utf-8")
        log.info("Convertido con pymupdf4llm: %s", out_path.name)
        return out_path
    except ImportError:
        pass

    # Intento 2: pdfminer.six
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        txt = extract_text(str(pdf_path))
        out_path.write_text(txt, encoding="utf-8")
        log.info("Convertido con pdfminer: %s", out_path.name)
        return out_path
    except ImportError:
        pass

    # Intento 3: pdftotext (poppler, CLI)
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(out_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            log.info("Convertido con pdftotext: %s", out_path.name)
            return out_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    log.error(
        "No se pudo convertir %s. Instala pymupdf4llm, pdfminer.six o poppler-utils.",
        pdf_path.name,
    )
    return None


# ── Main ─────────────────────────────────────────────────────────────────────


def find_md_files() -> list[Path]:
    """Busca todos los MDs de RAIAVL y RAIAVP en COMUNICADOS_DIR."""
    if not COMUNICADOS_DIR.exists():
        log.warning("Directorio no encontrado: %s", COMUNICADOS_DIR)
        return []
    patterns = [
        "*raiavl*.md",
        "*riavp*.md",
        "*raiavp*.md",
        "*ligero*rm*.md",
        "*pesado*rm*.md",
    ]
    found: list[Path] = []
    seen: set[Path] = set()
    for pat in patterns:
        for p in sorted(COMUNICADOS_DIR.glob(pat)):
            if p not in seen:
                found.append(p)
                seen.add(p)
    return found


def cmd_check() -> int:
    """Lista MDs disponibles y estado actual de los JSONs."""
    mds = find_md_files()
    if not mds:
        log.info("Sin MDs en %s", COMUNICADOS_DIR)
    for md in mds:
        result = parse_md(md)
        if result:
            print(f"  {md.name}  →  {result['indicador']}  {result['periodo']}  {result['datos']}")
        else:
            print(f"  {md.name}  →  parse fallido")

    for iid in ("autos_ligeros", "autos_pesados"):
        jpath = ROOT / "data" / f"{iid}.json"
        if jpath.exists():
            d = json.loads(jpath.read_text(encoding="utf-8"))
            series = d.get("series", [])
            ultimo = series[-1] if series else {}
            print(
                f"\n{iid}: {len(series)} periodos, ultimo={ultimo.get('Mes','?')}, "
                f"updated={d.get('ultima_actualizacion','?')}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Reporta cambios sin escribir")
    ap.add_argument("--check", action="store_true", help="Lista MDs y estado del JSON")
    ap.add_argument("--fetch", action="store_true", help="Descarga los PDFs más recientes del INEGI antes de ingestar")
    ap.add_argument("--pdf", metavar="PATH", help="Convierte un PDF y parsea antes de ingestar")
    args = ap.parse_args(argv)

    if args.check:
        return cmd_check()

    mds: list[Path] = []

    if args.pdf:
        # Un PDF específico provisto por el usuario
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            log.error("PDF no encontrado: %s", args.pdf)
            return 1
        md_path = pdf_to_md(pdf_path, COMUNICADOS_DIR)
        if not md_path:
            return 1
        mds = [md_path]
    elif args.fetch:
        # Descarga automática del PDF más reciente para cada indicador
        fetched_pdfs: list[Path] = []
        for indicador in ("autos_ligeros", "autos_pesados"):
            pdf_path = fetch_latest_pdf(indicador)
            if pdf_path:
                fetched_pdfs.append(pdf_path)
            else:
                log.warning("No se pudo descargar el PDF de %s", indicador)
        if not fetched_pdfs:
            log.error("No se descargó ningún PDF del INEGI")
            return 1
        # Convierte a MD los PDFs descargados
        for pdf_path in fetched_pdfs:
            md_path = pdf_to_md(pdf_path, COMUNICADOS_DIR)
            if md_path and md_path not in mds:
                mds.append(md_path)
        if not mds:
            log.error("No se generó ningún MD de los PDFs descargados")
            return 1
    else:
        mds = find_md_files()
        if not mds:
            log.warning(
                "Sin MDs en %s. Usa --fetch para descargar automáticamente, "
                "o --pdf ruta/al/boletin.pdf para un PDF específico.",
                COMUNICADOS_DIR,
            )
            return 1

    updated = 0
    for md in mds:
        result = parse_md(md)
        if not result:
            continue
        changed = upsert_json(
            result["indicador"],
            result["periodo"],
            result["datos"],
            result["fuente_md"],
            dry_run=args.dry_run,
        )
        if changed:
            updated += 1

    log.info(
        "%d/%d MDs procesados, %d con cambios%s",
        len(mds), len(mds), updated,
        " (dry-run)" if args.dry_run else "",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
