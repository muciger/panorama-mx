"""Scrape dirigido por subnodo. Extrae todos los IDs de cada subarbol relevante
para mapear los indicadores del tablero al BIE.

Genera config/bie_arbol/{nombre}.json para cada subarbol scrapeado.

Uso:
    python3 scripts/bie/scrape_subtrees.py             # todos los pendientes
    python3 scripts/bie/scrape_subtrees.py --solo X    # solo el subarbol X
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR / "scrapers"))
from scrape_bfs import fetch  # noqa: E402

# Subnodos del tema 1 (Coyuntura) y temas externos relevantes
SUBARBOLES = {
    "ind_ciclicos":         ("630",    "Indicadores ciclicos", 90),
    "ind_compuestos":       ("650",    "Indicadores compuestos coincidente y adelantado", 60),
    "consumo_privado":      ("605903", "Consumo privado", 90),
    "confianza_consumidor": ("3552",   "Confianza del consumidor", 120),
    "fbcf":                 ("606972", "FBCF", 120),
    "inpc":                 ("3623",   "Indices de precios", 180),
    "balanza_comercial":    ("3655",   "Balanza comercial", 180),
    "enoe_mensual":         ("2",      "ENOE mensual ocupacion", 200),
    "enoe_trimestral":      ("123",    "ENOE trimestral", 200),
    "emec":                 ("562654", "EMEC base 2018", 240),
    "ems":                  ("564077", "EMS base 2018", 240),
    "emim":                 ("542904", "EMIM serie 2018", 300),
    "enec":                 ("568505", "ENEC serie 2018", 180),
    "emoe":                 ("138032", "EMOE serie 2018", 240),
    "pib_trimestral":       ("600253", "PIB trimestral base 2018", 300),
    "actividad_industrial": ("606034", "Actividad industrial base 2018", 300),
    "imai_estatal":         ("607220", "Actividad industrial por entidad", 200),
    "itaee_estatal":        ("603944", "ITAEE base 2018", 150),
}


def scrape_subtree(root_id: str, root_name: str, token: str, time_limit: int, workers: int = 4) -> dict:
    queue = deque([(root_id, [root_name])])
    results = {}
    t0 = time.time()
    calls = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while queue and (time.time() - t0) < time_limit:
            batch = []
            while queue and len(batch) < workers:
                batch.append(queue.popleft())
            futures = {ex.submit(fetch, item[0], token): item for item in batch}
            for fut in as_completed(futures, timeout=20):
                try:
                    node_id, nodes = fut.result()
                except Exception:
                    continue
                path = futures[fut][1]
                calls += 1
                for n in nodes:
                    tipo = n.get("tipoNodo")
                    clave = n.get("claveSerie", "")
                    if tipo == "INDICADOR":
                        ind = n.get("indicador", {}) or {}
                        ind_id = str(ind.get("indicador", clave))
                        results[ind_id] = {
                            "nombre": ind.get("nombre", ""),
                            "ruta": path[:],
                        }
                    elif tipo == "TEMA":
                        t = n.get("tema", {}) or {}
                        nm = t.get("nombre", clave)
                        if t.get("hijos", 0) > 0 or t.get("numeroIndica", 0) > 0:
                            queue.append((clave, path + [nm]))
    return {
        "_meta": {
            "root_id": root_id, "root_name": root_name,
            "elapsed_s": round(time.time() - t0, 1),
            "calls": calls, "queue_restante": len(queue),
            "indicadores": len(results),
        },
        "indicadores": results,
    }


def load_env(root: Path) -> None:
    if "INEGI_BIE_TOKEN" in os.environ:
        return
    envf = root / ".env"
    if not envf.exists():
        return
    for line in envf.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", default=None, help="Solo un subarbol (clave de SUBARBOLES)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="Re-scrape incluso si ya existe")
    args = parser.parse_args()

    load_env(ROOT)
    token = os.environ.get("INEGI_BIE_TOKEN")
    if not token:
        print("ERROR: falta INEGI_BIE_TOKEN", file=sys.stderr)
        return 2

    out_dir = ROOT / "config" / "bie_arbol"
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [args.solo] if args.solo else list(SUBARBOLES.keys())
    for key in targets:
        if key not in SUBARBOLES:
            print(f"[skip] {key} no esta en SUBARBOLES")
            continue
        out_file = out_dir / f"{key}.json"
        if out_file.exists() and not args.force:
            print(f"[skip] {key} ya existe (usa --force para re-scrape)")
            continue

        root_id, root_name, time_limit = SUBARBOLES[key]
        print(f"\n=== {key} (tema {root_id}) ===  limite {time_limit}s")
        sys.stdout.flush()
        data = scrape_subtree(root_id, root_name, token, time_limit, args.workers)
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        m = data["_meta"]
        print(f"  -> {m['indicadores']} indicadores, {m['calls']} calls, {m['elapsed_s']}s, queue_restante={m['queue_restante']}")
        if m["queue_restante"] > 0:
            print(f"  ADVERTENCIA: scrape incompleto, faltan {m['queue_restante']} nodos")

    return 0


if __name__ == "__main__":
    sys.exit(main())
