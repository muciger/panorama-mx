"""Orquestador principal. Punto de entrada del pipeline.

Flujo:
1. Sincroniza calendario ICS oficial (calendar_sync.py)
2. Identifica indicadores con publicación reciente o atrasada
3. Descarga anexos XLSX (scraper.py)
4. Parsea y normaliza (parser.py)
5. Actualiza data/<indicador>.json con merge de series
6. Calcula benchmarks MA12 y evalúa thresholds
7. Regenera index.html (build.py)
8. Escribe log en logs/update_<fecha>.log

Uso:
    python scripts/update.py [--indicator <id>] [--force] [--dry-run]

Pendiente de implementación. Ver ARQUITECTURA.md sección 6.
"""

if __name__ == "__main__":
    raise NotImplementedError("Pendiente Fase 2-3. Ver ARQUITECTURA.md")
