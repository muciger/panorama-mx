"""Sincroniza el ICS oficial INEGI y regenera config/calendar.json.

Fuente: https://www.inegi.org.mx/contenidos/saladeprensa/doc/inegi.ics

Flujo:
1. Descarga ICS a cache/inegi.ics (o usa el cache si --offline)
2. Parsea eventos con icalendar
3. Mapea cada indicador de config/indicators.json a eventos via patron_ics (regex)
4. Genera config/calendar.json con ultima_publicacion_ics + proximas_publicaciones (hasta 6)
5. Reporta indicadores con 0 matches y publicaciones dentro del lookback reciente

Uso:
    python3 scripts/calendar_sync.py
    python3 scripts/calendar_sync.py --offline              # usa cache, no descarga
    python3 scripts/calendar_sync.py --lookback 7          # reporta últimas 7 días
    python3 scripts/calendar_sync.py --max-proximas 8      # genera más próximas
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from icalendar import Calendar
except ImportError:
    sys.stderr.write("Falta icalendar. Instala con: pip install icalendar\n")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
CACHE_ICS = ROOT / "cache" / "inegi.ics"
CONFIG_INDICATORS = ROOT / "config" / "indicators.json"
CONFIG_CALENDAR = ROOT / "config" / "calendar.json"
ICS_URL = "https://www.inegi.org.mx/contenidos/saladeprensa/doc/inegi.ics"
DEFAULT_MAX_PROXIMAS = 6
DEFAULT_LOOKBACK_DIAS = 3


def download_ics(url: str, dest: Path, timeout: int = 30) -> None:
    """Descarga ICS a disco. No sobreescribe si la descarga falla."""
    import urllib.request

    logging.info("Descargando %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "tablero-inegi/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if len(body) < 1000:
        raise RuntimeError(f"ICS sospechosamente chico ({len(body)} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    logging.info("Guardado %s (%d bytes)", dest, len(body))


def parse_ics(path: Path) -> list[dict]:
    """Devuelve lista de dicts con fecha (date) y summary (str) de cada VEVENT."""
    raw = path.read_bytes()
    cal = Calendar.from_ical(raw)
    out = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue
        dtstart = comp.get("dtstart")
        summary = comp.get("summary")
        if dtstart is None or summary is None:
            continue
        d = dtstart.dt
        if isinstance(d, datetime):
            d = d.date()
        elif not isinstance(d, date):
            continue
        out.append({"fecha": d, "summary": str(summary).strip()})
    out.sort(key=lambda x: x["fecha"])
    return out


def match_indicator(eventos: list[dict], patron: str) -> list[dict]:
    rgx = re.compile(patron, re.IGNORECASE)
    return [e for e in eventos if rgx.search(e["summary"])]


def build_entry(
    ind: dict,
    eventos: list[dict],
    hoy: date,
    max_proximas: int,
) -> dict:
    matches = match_indicator(eventos, ind["patron_ics"])
    pasadas = [e for e in matches if e["fecha"] < hoy]
    futuras_y_hoy = [e for e in matches if e["fecha"] >= hoy]
    ultima = pasadas[-1] if pasadas else None
    proximas = futuras_y_hoy[:max_proximas]
    return {
        "nombre": ind["nombre"],
        "categoria": ind["categoria"],
        "frecuencia": ind["frecuencia"],
        "patron_ics": ind["patron_ics"],
        "vinculado_con": ind.get("vinculado_con"),
        "ultima_publicacion_ics": {
            "fecha": ultima["fecha"].isoformat(),
            "evento_ics": ultima["summary"],
        } if ultima else None,
        "proximas_publicaciones": [
            {"fecha": e["fecha"].isoformat(), "evento_ics": e["summary"]}
            for e in proximas
        ],
        "matches_total": len(matches),
    }


def build_calendar_json(
    indicators_cfg: dict,
    eventos: list[dict],
    hoy: date,
    max_proximas: int,
    total_eventos: int,
) -> dict:
    out = {
        "_fuente": ICS_URL,
        "_generado": hoy.isoformat(),
        "_total_eventos_ics": total_eventos,
        "_fecha_corte": hoy.isoformat(),
        "indicadores": {},
    }
    for ind in indicators_cfg["indicadores"]:
        out["indicadores"][ind["id"]] = build_entry(ind, eventos, hoy, max_proximas)
    return out


def report_lookback(calendar: dict, hoy: date, lookback_dias: int) -> list[str]:
    """Devuelve ids con ultima_publicacion dentro de la ventana reciente."""
    cutoff = hoy - timedelta(days=lookback_dias)
    recientes = []
    for ind_id, entry in calendar["indicadores"].items():
        last = entry.get("ultima_publicacion_ics")
        if not last:
            continue
        fecha = date.fromisoformat(last["fecha"])
        if fecha >= cutoff:
            recientes.append((ind_id, last["fecha"], last["evento_ics"]))
    return recientes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Usa cache/inegi.ics, no descarga")
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DIAS)
    parser.add_argument("--max-proximas", type=int, default=DEFAULT_MAX_PROXIMAS)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.offline:
        try:
            download_ics(ICS_URL, CACHE_ICS)
        except Exception as exc:
            logging.warning("Descarga falló (%s). Uso cache existente.", exc)
            if not CACHE_ICS.exists():
                logging.error("No hay cache/inegi.ics. Abortando.")
                return 2

    if not CACHE_ICS.exists():
        logging.error("No existe %s. Corre sin --offline primero.", CACHE_ICS)
        return 2

    eventos = parse_ics(CACHE_ICS)
    logging.info("Eventos parseados: %d", len(eventos))

    indicators_cfg = json.loads(CONFIG_INDICATORS.read_text(encoding="utf-8"))
    hoy = date.today()

    calendar = build_calendar_json(
        indicators_cfg, eventos, hoy, args.max_proximas, len(eventos)
    )

    CONFIG_CALENDAR.write_text(
        json.dumps(calendar, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logging.info("Escrito %s con %d indicadores", CONFIG_CALENDAR, len(calendar["indicadores"]))

    sin_match = [
        ind_id for ind_id, e in calendar["indicadores"].items() if e["matches_total"] == 0
    ]
    if sin_match:
        logging.warning("Indicadores sin match: %s", ", ".join(sin_match))

    recientes = report_lookback(calendar, hoy, args.lookback)
    if recientes:
        logging.info("Publicaciones en últimos %d días:", args.lookback)
        for ind_id, fecha, evento in recientes:
            logging.info("  %s %s | %s", fecha, ind_id, evento[:80])

    return 0


if __name__ == "__main__":
    sys.exit(main())
