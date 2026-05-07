"""Tile-grid map de México por entidad federativa.

Cada estado se representa como un cuadrado en una rejilla geográfica
aproximada (estilo NYT, FT, Bloomberg). Más compacto y legible que un
GeoJSON real, sin depender de assets externos.

Usar build_tile_grid_svg(valores_por_entidad, options) para generar SVG inline.

Uso:
    from tile_map import build_tile_grid_svg
    svg = build_tile_grid_svg({"Aguascalientes": 5.2, ...}, unidad="%")
"""
from __future__ import annotations

from typing import Optional

# Posición (col, row) en grilla 8x7 que aproxima geografía de México
ENTIDAD_GRID = {
    "Baja California":      (0, 0),
    "Baja California Sur":  (0, 1),
    "Sonora":               (1, 0),
    "Sinaloa":              (1, 1),
    "Nayarit":              (2, 2),
    "Jalisco":              (2, 3),
    "Colima":               (2, 4),
    "Chihuahua":            (2, 0),
    "Durango":              (2, 1),
    "Zacatecas":            (3, 1),
    "Aguascalientes":       (3, 2),
    "Guanajuato":           (3, 3),
    "Michoacán":            (3, 4),
    "Guerrero":             (3, 5),
    "Coahuila":             (3, 0),
    "San Luis Potosí":      (4, 1),
    "Querétaro":            (4, 2),
    "México":               (4, 3),
    "Ciudad de México":     (4, 4),
    "Morelos":              (4, 5),
    "Oaxaca":               (4, 6),
    "Nuevo León":           (4, 0),
    "Tamaulipas":           (5, 0),
    "Hidalgo":              (5, 2),
    "Tlaxcala":             (5, 3),
    "Puebla":               (5, 4),
    "Veracruz":             (5, 1),
    "Tabasco":              (6, 5),
    "Campeche":             (6, 4),
    "Chiapas":              (6, 6),
    "Yucatán":              (7, 4),
    "Quintana Roo":         (7, 5),
}

# Abreviaturas oficiales 2-3 letras
ABBR = {
    "Aguascalientes": "AGS", "Baja California": "BC", "Baja California Sur": "BCS",
    "Campeche": "CAMP", "Coahuila": "COAH", "Colima": "COL",
    "Chiapas": "CHIS", "Chihuahua": "CHIH", "Ciudad de México": "CDMX",
    "Durango": "DGO", "Guanajuato": "GTO", "Guerrero": "GRO",
    "Hidalgo": "HGO", "Jalisco": "JAL", "México": "MEX",
    "Michoacán": "MICH", "Morelos": "MOR", "Nayarit": "NAY",
    "Nuevo León": "NL", "Oaxaca": "OAX", "Puebla": "PUE",
    "Querétaro": "QRO", "Quintana Roo": "QROO", "San Luis Potosí": "SLP",
    "Sinaloa": "SIN", "Sonora": "SON", "Tabasco": "TAB",
    "Tamaulipas": "TAM", "Tlaxcala": "TLAX", "Veracruz": "VER",
    "Yucatán": "YUC", "Zacatecas": "ZAC",
}


def _color_for_value(v: float, vmin: float, vmax: float, palette: str = "teal") -> str:
    """Devuelve color hex según valor en escala vmin-vmax."""
    if vmax == vmin:
        return "#E8E2DC"
    t = max(0, min(1, (v - vmin) / (vmax - vmin)))
    if palette == "teal":
        # crema → teal: #F4F0EC → #08989C
        r = int(244 + (8 - 244) * t)
        g = int(240 + (152 - 240) * t)
        b = int(236 + (156 - 236) * t)
    elif palette == "wine":
        r = int(244 + (155 - 244) * t)
        g = int(240 + (34 - 240) * t)
        b = int(236 + (71 - 236) * t)
    elif palette == "navy":
        r = int(244 + (0 - 244) * t)
        g = int(240 + (48 - 240) * t)
        b = int(236 + (87 - 236) * t)
    elif palette == "diverging":
        # diverging: wine → crema → teal
        if t < 0.5:
            t2 = t * 2
            r = int(155 + (244 - 155) * t2)
            g = int(34 + (240 - 34) * t2)
            b = int(71 + (236 - 71) * t2)
        else:
            t2 = (t - 0.5) * 2
            r = int(244 + (8 - 244) * t2)
            g = int(240 + (152 - 240) * t2)
            b = int(236 + (156 - 236) * t2)
    else:
        return "#E8E2DC"
    return f"#{r:02X}{g:02X}{b:02X}"


def build_tile_grid_svg(valores: dict, unidad: str = "", palette: str = "teal",
                        diverging_at_zero: bool = False, label_positivo: str = "alto",
                        label_negativo: str = "bajo") -> str:
    """Construye SVG inline con tile grid map.

    valores: {nombre_entidad: valor_numerico_o_None}
    palette: 'teal' (todo positivo), 'wine' (todo negativo), 'diverging' (con cero)
    diverging_at_zero: True si vmin/vmax incluye cero como punto medio
    """
    vals = [v for v in valores.values() if v is not None]
    if not vals:
        return '<div class="tile-map-empty">Sin datos disponibles</div>'

    if diverging_at_zero:
        m = max(abs(min(vals)), abs(max(vals)))
        vmin, vmax = -m, m
    else:
        vmin, vmax = min(vals), max(vals)

    cell_size = 56
    cell_gap = 4
    cell_total = cell_size + cell_gap
    cols = 8
    rows = 7
    width = cols * cell_total
    height = rows * cell_total

    cells = []
    for entidad, (row, col) in ENTIDAD_GRID.items():
        x = col * cell_total
        y = row * cell_total
        v = valores.get(entidad)
        abbr = ABBR.get(entidad, entidad[:3].upper())
        if v is None:
            color = "#F4F0EC"
            text_color = "#98989A"
            valor_label = "—"
        else:
            color = _color_for_value(v, vmin, vmax, palette)
            t = max(0, min(1, (v - vmin) / max(vmax - vmin, 1e-9)))
            text_color = "#fff" if t > 0.55 else "#1A1A1A"
            valor_label = f"{v:.1f}{unidad}" if unidad else f"{v:.1f}"
        title = f"{entidad}: {valor_label}"
        cells.append(
            f'<g class="tile-cell" data-entidad="{entidad}">'
            f'<title>{title}</title>'
            f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" rx="6" fill="{color}" stroke="#fff" stroke-width="1"/>'
            f'<text x="{x + cell_size/2}" y="{y + cell_size/2 - 4}" text-anchor="middle" fill="{text_color}" font-size="11" font-weight="600">{abbr}</text>'
            f'<text x="{x + cell_size/2}" y="{y + cell_size/2 + 12}" text-anchor="middle" fill="{text_color}" font-size="10" font-variant-numeric="tabular-nums">{valor_label}</text>'
            f'</g>'
        )

    # Leyenda
    legend_y = height + 12
    legend_w = 200
    legend_x = (width - legend_w) // 2
    grad_id = f"tg-grad-{palette}"
    if palette == "diverging":
        grad_stops = (
            f'<stop offset="0%" stop-color="{_color_for_value(vmin, vmin, vmax, palette)}"/>'
            f'<stop offset="50%" stop-color="{_color_for_value(0 if diverging_at_zero else (vmin+vmax)/2, vmin, vmax, palette)}"/>'
            f'<stop offset="100%" stop-color="{_color_for_value(vmax, vmin, vmax, palette)}"/>'
        )
    else:
        grad_stops = (
            f'<stop offset="0%" stop-color="{_color_for_value(vmin, vmin, vmax, palette)}"/>'
            f'<stop offset="100%" stop-color="{_color_for_value(vmax, vmin, vmax, palette)}"/>'
        )
    legend = (
        f'<defs><linearGradient id="{grad_id}" x1="0" x2="1">{grad_stops}</linearGradient></defs>'
        f'<rect x="{legend_x}" y="{legend_y}" width="{legend_w}" height="10" rx="3" fill="url(#{grad_id})"/>'
        f'<text x="{legend_x}" y="{legend_y + 26}" font-size="10.5" fill="#5C5C5C" text-anchor="start">'
        f'{vmin:.1f}{unidad} ({label_negativo})</text>'
        f'<text x="{legend_x + legend_w}" y="{legend_y + 26}" font-size="10.5" fill="#5C5C5C" text-anchor="end">'
        f'{label_positivo} ({vmax:.1f}{unidad})</text>'
    )

    return (
        f'<svg class="tile-map" viewBox="0 0 {width} {height + 38}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Mapa por entidad federativa">'
        f'{"".join(cells)}'
        f'{legend}'
        f'</svg>'
    )


if __name__ == "__main__":
    import sys
    test = {nombre: i * 1.5 for i, nombre in enumerate(ENTIDAD_GRID.keys())}
    print(build_tile_grid_svg(test, unidad="%", palette="teal"))
