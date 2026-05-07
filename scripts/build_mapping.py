"""
Helper para llenar config/bie_mapping.json.

Itera sobre todos los IDs de config/bie_lotes.json, consulta la API BIE una vez
por lote, y emite un CSV con el nombre oficial INEGI de cada serie. Sirve como
borrador que luego editas manualmente para asignar (indicador_local, columna).

Uso:
    export INEGI_BIE_TOKEN="<token>"
    python3 scripts/build_mapping.py > mapping_draft.csv
    # Después editas mapping_draft.csv en Excel y transpones al JSON.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

# Reutiliza el cliente
from ingest_bie import BIEClient, LOTES_PATH, id_de_serie, log


def nombre_de_serie(serie: dict) -> str:
    """Nombre oficial INEGI. El campo cambia según versión de la API."""
    for k in ("NOMBRE_INDICADOR", "NOMBRE", "nombreIndicador", "NombreIndicador"):
        if k in serie:
            return str(serie[k])
    # Fallback: inspeccionar cualquier campo con 'NOMBRE' o 'NAME'
    for k, v in serie.items():
        if "NOMBRE" in k.upper() or "NAME" in k.upper():
            return str(v)
    return "(sin nombre)"


def unidad_de_serie(serie: dict) -> str:
    for k in ("UNIDAD", "UNIDAD_MEDIDA", "UnidadMedida", "unidadMedida"):
        if k in serie:
            return str(serie[k])
    return ""


def ultimo_periodo(serie: dict) -> str:
    obs = serie.get("OBSERVATIONS", [])
    if not obs:
        return ""
    last = obs[-1]
    return f"{last.get('TIME_PERIOD', '')}={last.get('OBS_VALUE', '')}"


def main():
    token = os.environ.get("INEGI_BIE_TOKEN")
    if not token:
        print("ERROR: falta INEGI_BIE_TOKEN en entorno", file=sys.stderr)
        sys.exit(2)

    lotes_cfg = json.loads(Path(LOTES_PATH).read_text(encoding="utf-8"))
    client = BIEClient(token=token)

    writer = csv.writer(sys.stdout)
    writer.writerow(["lote", "frecuencia", "id_bie", "nombre_inegi", "unidad", "ultimo_valor", "indicador_local_sugerido", "columna_local_sugerida"])

    for nombre_lote, info in lotes_cfg["lotes"].items():
        data = client.fetch_batch(info["ids"])
        if data is None:
            log.error("Lote %s falló", nombre_lote)
            continue
        series = data.get("Series") or data.get("series") or []
        for s in series:
            sid = id_de_serie(s) or "?"
            writer.writerow([
                nombre_lote,
                info["frecuencia"],
                sid,
                nombre_de_serie(s),
                unidad_de_serie(s),
                ultimo_periodo(s),
                "",
                "",
            ])


if __name__ == "__main__":
    main()
