"""Parsers por indicador. Cada uno normaliza el XLSX de su boletín a schema canónico.

Schema de salida (ver ARQUITECTURA.md sección 5):
{
  "id": str,
  "series": [
    {"periodo": "mar-26", "<campo1>": val, "<campo2>": val, ...},
    ...
  ],
  "ultima_actualizacion": "YYYY-MM-DD"
}

Cada parser vive en una función separada:
- parse_inpc_mensual(xlsx_bytes) -> dict
- parse_igae(xlsx_bytes) -> dict
- ... (27 más)

Razón de no compartir un parser genérico: los anexos INEGI tienen formatos heterogéneos.
Algunos tienen hojas por sector, otros columnas múltiples. Parser por indicador es más robusto.

Uso:
    from parser import parse_indicator
    data = parse_indicator("inpc_mensual", xlsx_bytes)
"""

if __name__ == "__main__":
    raise NotImplementedError("Pendiente Fase 2.")
