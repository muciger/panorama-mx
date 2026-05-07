"""Descarga de anexos XLSX desde saladeprensa INEGI.

Para cada indicador con publicación reciente:
1. Abre la URL del boletín (config/indicators.json boletin_url)
2. Busca el link al anexo XLSX en el HTML (patrones conocidos)
3. Descarga el archivo a cache/downloads/<indicador>_<yyyymmdd>.xlsx
4. Retorna la ruta local para pasar al parser

Nota: la URL del boletín cambia con cada publicación. Fallback: buscar por nombre
del producto en saladeprensa si la URL fija devuelve 404.

Uso:
    python scripts/scraper.py --indicator inpc_mensual
"""

if __name__ == "__main__":
    raise NotImplementedError("Pendiente Fase 2.")
