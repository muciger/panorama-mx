"""
Scraper del árbol de indicadores del BIE del INEGI.
Recorre la API interna recursivamente y genera un mapa completo:
  { "clave_indicador": { "nombre": ..., "ruta": [...], "BD": ... } }

Uso:
    python scrape_tree.py --token TU_UUID
    python scrape_tree.py --token TU_UUID --tema 1    # Solo coyuntura (5,856 indicadores)
    python scrape_tree.py --token TU_UUID --tema all  # Todo el BIE (~88k indicadores)
"""

import json
import re
import sys
import time
import argparse
import requests


BASE = "https://www.inegi.org.mx/app/api/indicadores/interna_v1_3/API.svc/NodosTemas"
DEMO_TOKEN = "96fbd1bf-21e6-28e3-6e64-2b15999d2c89"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.inegi.org.mx/app/querybuilder2/default.html",
    "Origin": "https://www.inegi.org.mx",
}


def fetch_nodes(node_id: str, token: str, is_root: bool = False) -> list:
    """Llama al endpoint BIE y retorna la lista de nodos hijos."""
    if is_root:
        # geo=null, principales=1, tematica=3 (BIE), tipo=true
        url = f"{BASE}/null/es/null/null/null/1/3/true/null/405/json/{token}?callback=?"
    else:
        # geo=null, principales=null, tematica=3, tipo=true
        url = f"{BASE}/null/es/{node_id}/null/null/null/3/true/405/json/{token}?callback=?"

    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        text = r.text.strip()
        # Quitar wrapper JSONP: ?([...]);
        m = re.search(r"\?\((.*)\);?\s*$", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        return json.loads(text)
    except Exception as e:
        print(f"  ERROR en nodo {node_id}: {e}", file=sys.stderr)
        return []


def scrape_tree(
    node_id: str,
    path: list,
    results: dict,
    token: str,
    depth: int = 0,
    delay: float = 0.15,
) -> None:
    """
    Recorre el árbol recursivamente.
    results: dict acumulador { indicador_id: { nombre, ruta, BD } }
    """
    nodes = fetch_nodes(node_id, token, is_root=False)
    time.sleep(delay)

    for node in nodes:
        tipo = node.get("tipoNodo")
        clave = node.get("claveSerie", "")

        if tipo == "INDICADOR":
            ind = node.get("indicador", {}) or {}
            ind_id = str(ind.get("indicador", clave))
            nombre = ind.get("nombre", "")
            bd = ind.get("BD", "")
            results[ind_id] = {
                "nombre": nombre,
                "ruta": path[:],
                "BD": bd,
            }

        elif tipo == "TEMA":
            tema = node.get("tema", {}) or {}
            nombre_tema = tema.get("nombre", clave)
            bd = tema.get("BD", "")
            hijos = tema.get("hijos", 0)
            num_indica = tema.get("numeroIndica", 0)
            new_path = path + [nombre_tema]

            indent = "  " * depth
            print(
                f"{indent}[{bd}] {nombre_tema} "
                f"(hijos={hijos}, indicadores={num_indica}, "
                f"total_acum={len(results)})"
            )
            sys.stdout.flush()

            if hijos > 0 or num_indica > 0:
                scrape_tree(
                    clave, new_path, results,
                    token=token, depth=depth + 1, delay=delay
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--token", default=DEMO_TOKEN,
        help="UUID del token INEGI (default: token demo público)"
    )
    parser.add_argument(
        "--tema", default="1",
        help=(
            "Clave del tema raíz. Opciones clave:\n"
            "  1       = Indicadores económicos de coyuntura (5,856)\n"
            "  3817    = Ocupación y empleo (1,063)\n"
            "  671866  = Productividad base 2018 (4,730)\n"
            "  8061    = Cuentas nacionales (27,331)\n"
            "  19027   = Manufacturas (37,001)\n"
            "  36694   = Sector externo (8,782)\n"
            "  all     = Todo el BIE (~88k)\n"
            "Default: 1"
        )
    )
    parser.add_argument(
        "--delay", type=float, default=0.15,
        help="Segundos entre llamadas (default 0.15)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Archivo de salida JSON (default: indicadores_tema{TEMA}.json)"
    )
    args = parser.parse_args()

    token = args.token
    results = {}

    if args.tema == "all":
        output_file = args.output or "indicadores_bie_completo.json"
        print("Obteniendo todos los temas raíz del BIE...")
        root_nodes = fetch_nodes("root", token, is_root=True)
        print(f"  {len(root_nodes)} temas encontrados\n")

        for node in root_nodes:
            tema = node.get("tema", {}) or {}
            nombre = tema.get("nombre", "")
            clave = node.get("claveSerie", "")
            bd = tema.get("BD", "")
            hijos = tema.get("hijos", 0)
            num_indica = tema.get("numeroIndica", 0)
            print(
                f"[RAIZ] [{bd}] {nombre} "
                f"(clave={clave}, hijos={hijos}, indicadores={num_indica})"
            )
            scrape_tree(
                clave, [nombre], results,
                token=token, depth=1, delay=args.delay
            )
            print()

    else:
        # Scrape de un tema específico
        tema_id = args.tema
        output_file = args.output or f"indicadores_tema{tema_id}.json"
        print(f"Scrapeando tema {tema_id}...")
        nodes = fetch_nodes(tema_id, token, is_root=False)

        for node in nodes:
            tipo = node.get("tipoNodo")
            clave = node.get("claveSerie", "")
            if tipo == "TEMA":
                tema = node.get("tema", {}) or {}
                nombre = tema.get("nombre", "")
                print(f"  Subtema: {nombre}")
                scrape_tree(
                    clave,
                    [nombre],
                    results,
                    token=token,
                    depth=1,
                    delay=args.delay
                )
            elif tipo == "INDICADOR":
                ind = node.get("indicador", {}) or {}
                ind_id = str(ind.get("indicador", clave))
                results[ind_id] = {
                    "nombre": ind.get("nombre", ""),
                    "ruta": [],
                    "BD": ind.get("BD", ""),
                }

    # Guardar resultados
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\nTotal indicadores encontrados: {len(results)}")
    print(f"Guardado en: {output_file}")


if __name__ == "__main__":
    main()
