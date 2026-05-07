"""
Scraper BIE por chunks. Llama a un subtema específico y guarda en JSON.
Diseñado para caber en 40 segundos por llamada.

Uso:
    python scrape_chunk.py --token UUID --node CLAVE --path "Nombre del tema" --output archivo.json
"""

import asyncio
import aiohttp
import json
import re
import sys
import argparse
import time


BASE = "https://www.inegi.org.mx/app/api/indicadores/interna_v1_3/API.svc/NodosTemas"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.inegi.org.mx/app/querybuilder2/default.html",
    "Origin": "https://www.inegi.org.mx",
}


def parse_jsonp(text: str) -> list:
    text = text.strip()
    m = re.search(r"\?\((.*)\);?\s*$", text, re.DOTALL)
    if m:
        content = m.group(1).strip()
        # Formato de error: {ErrorCode: ...},STATUS
        err_m = re.match(r"^(\{.*\}),\d+$", content, re.DOTALL)
        if err_m:
            obj = json.loads(err_m.group(1))
            if obj.get("ErrorCode"):
                return []
            return [obj]
        return json.loads(content)
    return json.loads(text)


async def fetch_nodes(session, node_id, token, semaphore, retries=2):
    url = f"{BASE}/null/es/{node_id}/null/null/null/3/true/405/json/{token}?callback=?"
    for attempt in range(retries + 1):
        async with semaphore:
            try:
                async with session.get(
                    url, headers=HEADERS,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    text = await resp.text()
                    return parse_jsonp(text)
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                else:
                    print(f"  FAIL {node_id}: {e}", file=sys.stderr)
                    return []


async def scrape_node(session, node_id, path, results, token, semaphore, depth=0):
    nodes = await fetch_nodes(session, node_id, token, semaphore)
    tasks = []

    for node in nodes:
        tipo = node.get("tipoNodo")
        clave = node.get("claveSerie", "")

        if tipo == "INDICADOR":
            ind = node.get("indicador", {}) or {}
            ind_id = str(ind.get("indicador", clave))
            results[ind_id] = {
                "nombre": ind.get("nombre", ""),
                "ruta": path[:],
                "BD": ind.get("BD", ""),
            }

        elif tipo == "TEMA":
            tema = node.get("tema", {}) or {}
            nombre_tema = tema.get("nombre", clave)
            hijos = tema.get("hijos", 0)
            num_indica = tema.get("numeroIndica", 0)
            new_path = path + [nombre_tema]
            if hijos > 0 or num_indica > 0:
                tasks.append(
                    scrape_node(session, clave, new_path, results, token, semaphore, depth + 1)
                )

    if tasks:
        await asyncio.gather(*tasks)


async def main_async(token, node_id, path_list):
    semaphore = asyncio.Semaphore(4)
    connector = aiohttp.TCPConnector(limit=10)
    results = {}

    async with aiohttp.ClientSession(connector=connector) as session:
        await scrape_node(session, node_id, path_list, results, token, semaphore)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--node", required=True, help="Clave del nodo a scrapear")
    parser.add_argument("--path", default="", help="Ruta base separada por '|'")
    parser.add_argument("--output", required=True)
    parser.add_argument("--merge", default=None, help="JSON existente donde hacer merge")
    args = parser.parse_args()

    path_list = [p for p in args.path.split("|") if p] if args.path else []

    t0 = time.time()
    results = asyncio.run(main_async(args.token, args.node, path_list))
    elapsed = time.time() - t0

    # Merge con archivo existente si se especificó
    if args.merge:
        try:
            with open(args.merge, "r", encoding="utf-8") as f:
                existing = json.load(f)
            existing.update(results)
            results = existing
        except FileNotFoundError:
            pass

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"chunk={args.node} indicadores={len(results)} tiempo={elapsed:.1f}s archivo={args.output}")


if __name__ == "__main__":
    main()
