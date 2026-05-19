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

ROOT = Path(__file__).resolve().parent.parent
CACHE_ICS = ROOT / "cache" / "inegi.ics"
CONFIG_INDICATORS = ROOT / "config" / "indicators.json"
CONFIG_CALENDAR = ROOT / "config" / "calendar.json"
ICS_URL = "https://www.inegi.org.mx/contenidos/saladeprensa/doc/inegi.ics"
DEFAULT_MAX_PROXIMAS = 6
DEFAULT_LOOKBACK_DIAS = 3

# Fechas suplementarias para indicadores no capturados por el ICS oficial.
# Fuente: Calendario de Difusión INEGI 2026 (PDF oficial) e IMSS.
# Actualizar manualmente cada enero cuando INEGI publique el nuevo calendario.
SUPPLEMENTAL_DATES: dict[str, dict] = {
    # IOAE: clasificado como "Información Experimental" por INEGI, no aparece en el ICS.
    # Fuente: cal_2026.pdf, sección "Información Experimental", fila IOAE.
    "igae_ioae_resumen": {
        "label": "Indicador Oportuno de la Actividad Económica (IOAE)",
        "fechas": [
            "2026-01-21", "2026-02-20", "2026-03-20", "2026-04-20",
            "2026-05-19", "2026-06-17", "2026-07-21", "2026-08-20",
            "2026-09-22", "2026-10-20", "2026-11-19", "2026-12-18",
        ],
    },
    # IMSS: publica estadísticas de empleo mensualmente, aprox. día 12.
    # No aparece en el calendario INEGI. Fechas ajustadas al lunes siguiente
    # cuando el 12 cae en fin de semana.
    "empleo_imss": {
        "label": "Informe mensual de empleo IMSS",
        "fechas": [
            "2026-01-12", "2026-02-12", "2026-03-12", "2026-04-13",
            "2026-05-12", "2026-06-12", "2026-07-13", "2026-08-12",
            "2026-09-14", "2026-10-12", "2026-11-12", "2026-12-14",
        ],
    },
}


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
    """Parser ICS con stdlib (sin dependencia icalendar). Devuelve lista de eventos
    con fecha (date) y summary (str). Maneja line folding RFC 5545."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Unfold: líneas que empiezan con espacio o tab continúan la anterior.
    lines: list[str] = []
    for line in raw.splitlines():
        if (line.startswith(" ") or line.startswith("\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)

    out: list[dict] = []
    cur: dict = {}
    in_event = False
    for line in lines:
        if line.startswith("BEGIN:VEVENT"):
            in_event = True
            cur = {}
        elif line.startswith("END:VEVENT"):
            if in_event and cur.get("fecha") and cur.get("summary"):
                out.append(cur)
            in_event = False
        elif in_event:
            if line.startswith("DTSTART"):
                m = re.search(r":(\d{8})", line)
                if m:
                    s = m.group(1)
                    try:
                        cur["fecha"] = date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
                    except ValueError:
                        pass
            elif line.startswith("SUMMARY"):
                # Unescape \, y \;
                summary = line.split(":", 1)[1].strip() if ":" in line else ""
                summary = summary.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
                cur["summary"] = summary
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
    patron = ind.get("patron_ics")
    if not patron:
        return {
            "nombre": ind["nombre"],
            "categoria": ind["categoria"],
            "frecuencia": ind["frecuencia"],
            "patron_ics": None,
            "vinculado_con": ind.get("vinculado_con"),
            "ultima_publicacion_ics": None,
            "proximas_publicaciones": [],
            "matches_total": 0,
        }
    matches = match_indicator(eventos, patron)
    pasadas = [e for e in matches if e["fecha"] < hoy]
    futuras_y_hoy = [e for e in matches if e["fecha"] >= hoy]
    ultima = pasadas[-1] if pasadas else None
    proximas = futuras_y_hoy[:max_proximas]
    return {
        "nombre": ind["nombre"],
        "categoria": ind["categoria"],
        "frecuencia": ind["frecuencia"],
        "patron_ics": patron,
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


def merge_supplemental(calendar: dict, hoy: date, max_proximas: int) -> None:
    """Inyecta fechas suplementarias en indicadores no cubiertos por el ICS.

    Para indicadores sin match ICS (matches_total == 0): reemplaza
    proximas_publicaciones y ultima_publicacion_ics con los datos suplementarios.
    Para indicadores con match ICS: mezcla las fechas suplementarias con las
    del ICS, ordena por fecha y recorta a max_proximas.
    Modifica calendar en-place.
    """
    for ind_id, sup in SUPPLEMENTAL_DATES.items():
        entry = calendar["indicadores"].get(ind_id)
        if not entry:
            continue

        sup_futuras = [
            {"fecha": f, "evento_ics": sup["label"]}
            for f in sup["fechas"]
            if date.fromisoformat(f) >= hoy
        ]
        sup_pasadas = [f for f in sup["fechas"] if date.fromisoformat(f) < hoy]

        if entry["matches_total"] == 0:
            entry["proximas_publicaciones"] = sup_futuras[:max_proximas]
            if sup_pasadas and not entry.get("ultima_publicacion_ics"):
                entry["ultima_publicacion_ics"] = {
                    "fecha": sup_pasadas[-1],
                    "evento_ics": sup["label"],
                }
        else:
            merged = sorted(
                sup_futuras + entry["proximas_publicaciones"],
                key=lambda x: x["fecha"],
            )
            seen: set[str] = set()
            deduped = []
            for e in merged:
                if e["fecha"] not in seen:
                    seen.add(e["fecha"])
                    deduped.append(e)
            entry["proximas_publicaciones"] = deduped[:max_proximas]


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
    # Horario del centro de México: el runner cloud corre en UTC y cerca de
    # medianoche CST clasificaría eventos "de hoy" como pasados/futuros.
    try:
        from zoneinfo import ZoneInfo
        hoy = datetime.now(ZoneInfo("America/Mexico_City")).date()
    except Exception:
        hoy = date.today()

    calendar = build_calendar_json(
        indicators_cfg, eventos, hoy, args.max_proximas, len(eventos)
    )
    merge_supplemental(calendar, hoy, args.max_proximas)

    _tmp_cal = CONFIG_CALENDAR.with_name(CONFIG_CALENDAR.name + ".tmp")
    _tmp_cal.write_text(
        json.dumps(calendar, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _tmp_cal.replace(CONFIG_CALENDAR)
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
