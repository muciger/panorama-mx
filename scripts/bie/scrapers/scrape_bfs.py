"""
BFS scraper con checkpoint. Cada ejecucion avanza hasta el tiempo limite
y guarda el estado. Volver a correr continua donde quedo.

Uso:
    python scrape_bfs.py --token UUID --start 1 --output coyuntura.json
    (Ejecutar varias veces hasta que reporte complete=True)
"""

import requests
import json
import re
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque

TOKEN_DEFAULT = "96fbd1bf-21e6-28e3-6e64-2b15999d2c89"
BASE = "https://www.inegi.org.mx/app/api/indicadores/interna_v1_3/API.svc/NodosTemas"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.inegi.org.mx/app/querybuilder2/default.html",
    "Origin": "https://www.inegi.org.mx",
}


def fetch(node_id, token):
    url = f"{BASE}/null/es/{node_id}/null/null/null/3/true/405/json/{token}?callback=?"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        text = r.text.strip()
        m = re.search(r"\?\((.*)\)", text, re.DOTALL)
        if not m:
            return node_id, []
        content = m.group(1).strip()
        em = re.match(r"^(\{.*\}),\d+$", content, re.DOTALL)
        if em:
            obj = json.loads(em.group(1))
            return node_id, [] if obj.get("ErrorCode") else [obj]
        return node_id, json.loads(content)
    except Exception as e:
        print(f"  ERR {node_id}: {e}", file=sys.stderr)
        return node_id, []


def run_chunk(token, queue, results, time_limit=36, workers=4):
    """
    Procesa la queue hasta que se agote el tiempo.
    Modifica queue y results in-place.
    """
    t0 = time.time()
    calls = 0

    with ThreadPoolExecutor(max_workers=workers) as ex:
        while queue and (time.time() - t0) < time_limit:
            batch = []
            while queue and len(batch) < workers:
                batch.append(queue.popleft())

            futures = {ex.submit(fetch, item[0], token): item for item in batch}
            for fut in as_completed(futures, timeout=15):
                try:
                    node_id, nodes = fut.result()
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
                                "BD": ind.get("BD", ""),
                            }
                        elif tipo == "TEMA":
                            t = n.get("tema", {}) or {}
                            nm = t.get("nombre", clave)
                            if t.get("hijos", 0) > 0 or t.get("numeroIndica", 0) > 0:
                                queue.append((clave, path + [nm]))
                except Exception as e:
                    print(f"  future ERR: {e}", file=sys.stderr)

    return calls, time.time() - t0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=TOKEN_DEFAULT)
    parser.add_argument("--start", default=None,
                        help="Clave del nodo raiz (solo para inicio, no para resume)")
    parser.add_argument("--start-name", default="",
                        help="Nombre legible del nodo raiz")
    parser.add_argument("--output", default="indicadores.json")
    parser.add_argument("--checkpoint", default=None,
                        help="Archivo de checkpoint (default: output + .ckpt)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--time-limit", type=float, default=36,
                        help="Segundos maximos por ejecucion (default 36)")
    args = parser.parse_args()

    ckpt_file = args.checkpoint or (args.output + ".ckpt")

    # Cargar checkpoint si existe
    results = {}
    queue = deque()

    if __import__("os").path.exists(ckpt_file):
        with open(ckpt_file, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
        results = ckpt.get("results", {})
        queue = deque([(item["node"], item["path"]) for item in ckpt.get("queue", [])])
        print(f"Resume: {len(results)} indicadores, {len(queue)} nodos en queue")
    elif args.start:
        queue.append((args.start, [args.start_name] if args.start_name else []))
        print(f"Inicio desde nodo {args.start}")
    else:
        print("ERROR: necesitas --start para la primera ejecucion o --checkpoint existente")
        sys.exit(1)

    # Correr chunk
    calls, elapsed = run_chunk(args.token, queue, results,
                               time_limit=args.time_limit, workers=args.workers)

    complete = len(queue) == 0

    # Guardar resultados parciales
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Guardar checkpoint si no completó
    if not complete:
        ckpt_data = {
            "results": results,
            "queue": [{"node": item[0], "path": item[1]} for item in queue],
        }
        with open(ckpt_file, "w", encoding="utf-8") as f:
            json.dump(ckpt_data, f, ensure_ascii=False)
    else:
        # Borrar checkpoint si completó
        import os
        if os.path.exists(ckpt_file):
            os.remove(ckpt_file)

    print(
        f"calls={calls} elapsed={elapsed:.1f}s "
        f"indicadores={len(results)} "
        f"queue_restante={len(queue)} "
        f"complete={complete}"
    )
    print(f"Guardado: {args.output}")
    if not complete:
        print("Vuelve a ejecutar para continuar.")


if __name__ == "__main__":
    main()
