"""
Cliente de ingesta BIE INEGI para el Tablero de Indicadores.

Flujo:
1. Lee config/bie_lotes.json (lotes por frecuencia) y config/bie_mapping.json (ID BIE -> columna local).
2. Hace requests batch a la API BIE (múltiples IDs por URL, separados por coma).
3. Aplica normalización de fecha ramificada por frecuencia (M/T/A/Q).
4. Pivotea las series a la estructura local (periodo x columna) y escribe JSONs en data/.
5. Cache on-disk con TTL para evitar llamadas repetidas en un mismo día.
6. Retry con backoff exponencial y rate limit conservador.

Uso:
    export INEGI_BIE_TOKEN="<tu-token>"
    python3 scripts/ingest_bie.py                  # ingesta completa
    python3 scripts/ingest_bie.py --lote igae_y_ioae_mensual   # un lote
    python3 scripts/ingest_bie.py --dry-run        # no escribe JSONs
    python3 scripts/ingest_bie.py --no-cache       # forza refetch

Dependencias: requests, python-dateutil (opcionales: ninguna más).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

# Rutas base, relativas al repo
ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache" / "bie"
LOG_DIR = ROOT / "logs"

LOTES_PATH = CONFIG_DIR / "bie_lotes.json"
MAPPING_PATH = CONFIG_DIR / "bie_mapping.json"

BIE_BASE = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR"
DEFAULT_GEO = "00"          # Nacional
DEFAULT_SOURCE = "BIE-BISE" # Base de INEGI: BIE-BISE para indicadores económicos (BISE devuelve error)
CACHE_TTL_HOURS = 6
RATE_LIMIT_SECONDS = 0.25
REQUEST_TIMEOUT = 20

# Mapeo FREQ (código numérico BISE) -> frecuencia canónica del pipeline
FREQ_BISE_A_LOCAL = {
    "1": "A",   # Anual
    "4": "Q",   # Quincenal (a validar contra muestra real)
    "6": "T",   # Trimestral
    "7": "M",   # Mensual
    "8": "M",   # Mensual alternativa
}

MESES_ES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

# ---------- Logging ----------

def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "ingest_bie.log"
    logger = logging.getLogger("ingest_bie")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = setup_logging()


# ---------- Normalización de fechas ----------

def parse_bie_period(raw: str, frecuencia: str) -> datetime | None:
    """Convierte TIME_PERIOD del BIE a datetime según frecuencia.

    Frecuencias:
      - M: formato 'YYYY/MM' -> primer día del mes.
      - T: formato 'YYYY/QQ' con QQ en 01-04 -> último mes del trimestre (Mar, Jun, Sep, Dic).
      - A: formato 'YYYY' -> 1 de enero.
      - Q (quincenal): formato esperado 'YYYY/MM/QQ' con QQ en 01 o 02.
           Q1=día 1, Q2=día 15 (convención aproximada para ordenar).
           NOTA: validar con respuesta real de INPC quincenal antes de asumir este formato.
    """
    if raw is None:
        return None
    raw = raw.strip()
    try:
        if frecuencia == "M":
            return datetime.strptime(raw, "%Y/%m")
        if frecuencia == "T":
            anio, q = raw.split("/")
            q = int(q)
            mes_cierre = {1: 3, 2: 6, 3: 9, 4: 12}[q]
            return datetime(int(anio), mes_cierre, 1)
        if frecuencia == "A":
            return datetime(int(raw), 1, 1)
        if frecuencia == "Q":
            # Intento 1: 'YYYY/MM/QQ'
            parts = raw.split("/")
            if len(parts) == 3:
                anio, mes, q = parts
                dia = 1 if q == "01" else 15
                return datetime(int(anio), int(mes), dia)
            # Intento 2: 'YYYY/QQQ' con QQQ en 01-24 (quincena del año)
            if len(parts) == 2:
                anio, qq = parts
                qq = int(qq)
                mes = ((qq - 1) // 2) + 1
                dia = 1 if qq % 2 == 1 else 15
                return datetime(int(anio), mes, dia)
    except (ValueError, KeyError) as e:
        log.warning("No pude parsear periodo raw=%r freq=%s: %s", raw, frecuencia, e)
    return None


def format_periodo_local(fecha: datetime, periodo_format: str) -> str:
    """Convierte datetime al string que usa el JSON local."""
    if periodo_format == "mmm-yy":
        return f"{MESES_ES[fecha.month]}-{fecha.year % 100:02d}"
    if periodo_format == "T-YY":
        q = (fecha.month - 1) // 3 + 1
        return f"T{q}-{fecha.year % 100:02d}"
    if periodo_format == "YYYY":
        return str(fecha.year)
    if periodo_format == "QNN-yy":
        # quincena: numerada 1-24 dentro del año
        qn = (fecha.month - 1) * 2 + (1 if fecha.day <= 7 else 2)
        return f"Q{qn:02d}-{fecha.year % 100:02d}"
    return fecha.strftime("%Y-%m-%d")


# ---------- Cliente BIE ----------

@dataclass
class BIEClient:
    token: str
    geo: str = DEFAULT_GEO
    source: str = DEFAULT_SOURCE
    cache_dir: Path = CACHE_DIR
    cache_ttl: timedelta = timedelta(hours=CACHE_TTL_HOURS)
    max_retries: int = 3
    rate_limit: float = RATE_LIMIT_SECONDS
    _last_request: float = field(default=0.0, init=False)

    def __post_init__(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, ids: list[str], geo: str) -> Path:
        raw = f"{geo}|{','.join(sorted(ids))}"
        h = hashlib.md5(raw.encode()).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _cache_fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        return age < self.cache_ttl

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request = time.monotonic()

    def fetch_batch(self, ids: list[str], geo: str | None = None, use_cache: bool = True) -> dict[str, Any] | None:
        """Trae un lote de IDs. Maneja cache, retry y rate limit."""
        geo = geo or self.geo
        cache_path = self._cache_key(ids, geo)
        if use_cache and self._cache_fresh(cache_path):
            log.info("Cache hit %s (%d IDs)", cache_path.name, len(ids))
            return json.loads(cache_path.read_text(encoding="utf-8"))

        ids_str = ",".join(ids)
        url = f"{BIE_BASE}/{ids_str}/es/{geo}/false/{self.source}/2.0/{self.token}?type=json"

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                log.info("GET lote %d IDs geo=%s intento=%d", len(ids), geo, attempt)
                resp = requests.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data
            except requests.exceptions.RequestException as e:
                wait = 2 ** attempt
                msg = str(e).replace(self.token, "***") if self.token else str(e)
                log.warning("Error en lote (intento %d/%d): %s. Backoff %ds", attempt, self.max_retries, msg, wait)
                time.sleep(wait)
        log.error("Agotados retries en lote de %d IDs", len(ids))
        return None


# ---------- Pivot y escritura ----------

def observaciones_de_serie(serie: dict) -> list[tuple[str, str]]:
    """Extrae lista de (TIME_PERIOD, OBS_VALUE) de una serie BIE."""
    obs = serie.get("OBSERVATIONS", [])
    return [(o.get("TIME_PERIOD"), o.get("OBS_VALUE")) for o in obs]


def id_de_serie(serie: dict) -> str | None:
    """BIE a veces usa 'INDICADOR' o 'INDICATOR'. Intenta ambos."""
    for k in ("INDICADOR", "INDICATOR", "idIndicador"):
        if k in serie:
            return str(serie[k])
    return None


def ensamblar_indicador(
    indicador_id: str,
    cfg_indicador: dict,
    series_bie_por_id: dict[str, dict],
) -> dict | None:
    """Construye el dict (periodos, series, columnas) para un indicador local.

    Pivotea las series BIE a filas por periodo, columnas por nombre local.
    """
    series_map: dict[str, str] = cfg_indicador.get("series_map", {})
    if not series_map:
        log.warning("Indicador %s sin series_map, omitido", indicador_id)
        return None

    freq_bie = cfg_indicador["frecuencia_bie"]
    periodo_format = cfg_indicador["periodo_format"]
    columnas_locales = list(series_map.values())

    # Recolectar todas las fechas observadas en todas las series mapeadas
    filas_por_fecha: dict[datetime, dict[str, Any]] = {}
    for bie_id, col_local in series_map.items():
        serie = series_bie_por_id.get(bie_id)
        if serie is None:
            log.warning("ID %s no devuelto por BIE para %s (%s)", bie_id, indicador_id, col_local)
            continue
        for raw_periodo, raw_valor in observaciones_de_serie(serie):
            fecha = parse_bie_period(raw_periodo, freq_bie)
            if fecha is None:
                continue
            try:
                valor = float(raw_valor) if raw_valor not in (None, "") else None
            except ValueError:
                valor = None
            fila = filas_por_fecha.setdefault(fecha, {})
            fila[col_local] = valor

    if not filas_por_fecha:
        log.warning("Indicador %s sin observaciones ensambladas", indicador_id)
        return None

    # Ordenar por fecha ascendente y formatear periodos
    fechas_ord = sorted(filas_por_fecha.keys())
    periodos = [format_periodo_local(f, periodo_format) for f in fechas_ord]

    label_periodo = {"mensual": "Mes", "trimestral": "Trimestre", "anual": "Anio", "quincenal": "Quincena"}[cfg_indicador["frecuencia_local"]]

    series_out = []
    for fecha in fechas_ord:
        fila_out = {label_periodo: format_periodo_local(fecha, periodo_format)}
        fila = filas_por_fecha[fecha]
        for col in columnas_locales:
            fila_out[col] = fila.get(col)
        series_out.append(fila_out)

    return {
        "periodos": periodos,
        "series": series_out,
        "columnas": [label_periodo] + columnas_locales,
        "label_periodo": label_periodo,
    }


def _write_json_atomic(path: Path, obj: Any) -> None:
    """Escritura atómica (tmp + rename): un crash a mitad no trunca el JSON bueno."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


_PERIODO_KEYS = {"Periodo", "Mes", "Trimestre", "Anio", "Quincena", "Entidad"}


def _celdas_con_valor(d: dict) -> int:
    """Celdas con dato real (no None) en series, ignorando llaves de periodo.
    Misma lógica que bie/ingest.py:guarda_segura para mantener consistencia."""
    n = 0
    for fila in (d.get("series") or []):
        if not isinstance(fila, dict):
            continue
        for k, v in fila.items():
            if v is None or k in _PERIODO_KEYS:
                continue
            n += 1
    return n


def _guarda_segura(out_path: Path, nuevo: dict) -> tuple[bool, str]:
    """Rechaza sobrescribir si la respuesta BIE viene vacía o encoge >50% vs el
    archivo existente. Defensa contra respuestas parciales (geo-block: HTTP 200
    con cuerpo vacío) que ya destruyeron datos buenos en un run previo."""
    cells_new = _celdas_con_valor(nuevo)
    if not (nuevo.get("periodos") or nuevo.get("series")) or cells_new == 0:
        return False, "respuesta vacía o sin valores"
    if out_path.exists():
        try:
            viejo = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            viejo = {}
        cells_old = _celdas_con_valor(viejo)
        if cells_old >= 8 and cells_new < cells_old * 0.5:
            return False, f"celdas con dato {cells_old} -> {cells_new} (>50% perdido)"
    return True, ""


def merge_con_json_local(indicador_id: str, ensamble: dict, dry_run: bool = False) -> Path | None:
    """Escribe el ensamble en data/<indicador>.json preservando metadatos existentes.

    Si el JSON local existe, conserva campos meta y reemplaza 'periodos', 'series', 'columnas'.
    Si no existe, crea uno mínimo.
    """
    out_path = DATA_DIR / f"{indicador_id}.json"

    if out_path.exists():
        current = json.loads(out_path.read_text(encoding="utf-8"))
    else:
        current = {
            "id": indicador_id,
            "nombre": indicador_id,
            "categoria": "por_asignar",
            "frecuencia": "por_asignar",
            "unidad": "por_asignar",
        }

    current["periodos"] = ensamble["periodos"]
    current["series"] = ensamble["series"]
    current["columnas"] = ensamble["columnas"]
    if "columnas_normalizadas" not in current:
        current["columnas_normalizadas"] = ensamble["columnas"]
    current["ultima_actualizacion"] = datetime.now().strftime("%Y-%m-%d")
    current["fuente_ingesta"] = "bie_api"

    ok, motivo = _guarda_segura(out_path, current)
    if not ok:
        log.error("%s: NO se sobrescribe (%s)", out_path.name, motivo)
        return None

    if dry_run:
        log.info("DRY RUN: no escribe %s (%d periodos)", out_path.name, len(ensamble["periodos"]))
        return None

    _write_json_atomic(out_path, current)
    log.info("Escrito %s con %d periodos, %d columnas", out_path.name, len(ensamble["periodos"]), len(ensamble["columnas"]))
    return out_path


# ---------- Orquestación ----------

def cargar_configs() -> tuple[dict, dict]:
    lotes = json.loads(LOTES_PATH.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    return lotes, mapping


def run(lote_filter: str | None = None, dry_run: bool = False, use_cache: bool = True) -> int:
    token = os.environ.get("INEGI_BIE_TOKEN")
    if not token:
        log.error("Falta INEGI_BIE_TOKEN en el entorno. export INEGI_BIE_TOKEN=...")
        return 2

    lotes_cfg, mapping_cfg = cargar_configs()
    lotes = lotes_cfg["lotes"]
    indicadores_map = mapping_cfg["indicadores"]

    if lote_filter:
        if lote_filter not in lotes:
            log.error("Lote %s no existe. Opciones: %s", lote_filter, list(lotes.keys()))
            return 3
        lotes = {lote_filter: lotes[lote_filter]}

    client = BIEClient(token=token)

    # 1. Traer todas las series, indexadas por ID
    series_bie_por_id: dict[str, dict] = {}
    for nombre_lote, info in lotes.items():
        log.info("=== Lote %s (freq=%s, %d IDs) ===", nombre_lote, info["frecuencia"], len(info["ids"]))
        data = client.fetch_batch(info["ids"], use_cache=use_cache)
        if data is None:
            log.error("Lote %s fallido, se omite", nombre_lote)
            continue
        series = data.get("Series") or data.get("series") or []
        for s in series:
            sid = id_de_serie(s)
            if sid:
                series_bie_por_id[sid] = s
        log.info("Lote %s: %d series recibidas", nombre_lote, len(series))

    log.info("Total series BIE indexadas: %d", len(series_bie_por_id))

    # 2. Por cada indicador local, ensamblar JSON
    escritos = 0
    omitidos = 0
    rechazos = 0
    for indicador_id, cfg in indicadores_map.items():
        ensamble = ensamblar_indicador(indicador_id, cfg, series_bie_por_id)
        if ensamble is None:
            omitidos += 1
            continue
        resultado = merge_con_json_local(indicador_id, ensamble, dry_run=dry_run)
        if resultado is None and not dry_run:
            # None en modo real solo ocurre por rechazo de _guarda_segura.
            rechazos += 1
            continue
        escritos += 1

    log.info(
        "Ingesta finalizada: %d escritos, %d omitidos, %d rechazados por guarda",
        escritos, omitidos, rechazos,
    )
    return 1 if rechazos else 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lote", help="Filtra a un solo lote (nombre del key en bie_lotes.json)")
    p.add_argument("--dry-run", action="store_true", help="No escribe JSONs")
    p.add_argument("--no-cache", action="store_true", help="Ignora cache local, refetch")
    args = p.parse_args()
    sys.exit(run(lote_filter=args.lote, dry_run=args.dry_run, use_cache=not args.no_cache))


if __name__ == "__main__":
    main()
