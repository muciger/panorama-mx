# Estilo definitivo para interpretaciones del tablero Panorama MX

Esta es la fuente de verdad del tono, vocabulario y estructura que debe usar el modelo al generar las interpretaciones de cada indicador. Calibrado contra el documento "Seguimiento de coyuntura económica" del 8 de mayo de 2026 (V3.1), confirmado por Germán como estilo definitivo.

## Audiencia

Subsecretaría de Economía. Lectora con responsabilidad ejecutiva pero sin formación académica formal en economía. Necesita comprender qué muestran los datos, qué significan y qué implican para política pública. No tolera jerga sin explicación. Espera precisión, números defendibles y argumentos conectados.

## Reglas duras

1. Prosa expositiva. Sin viñetas, sin listas, sin headings dentro del texto.
2. Voz activa. Sujetos económicos concretos (empresas, hogares, gobierno, Banco de México, sector externo) en lugar de abstracciones pasivas.
3. Acrónimos siempre con expansión y descripción funcional al primer uso por bloque. "Formación Bruta de Capital Fijo, que mide la inversión que realizan empresas y gobierno en maquinaria, equipo, plantas y construcción".
4. Cada dato cuantitativo va con su significado interpretado. No basta con "cayó 3.6%". Hay que explicar qué implica esa caída en términos de capacidad productiva, demanda, empleo, precios, según el caso.
5. Términos técnicos traducidos en línea cuando se necesiten. Ejemplo: "holgura en la economía, es decir, una menor utilización de capacidad productiva".
6. Comparaciones de magnitud con anclaje. "Por debajo de los 50 puntos, nivel que normalmente separa expansión de contracción".
7. Conexiones causales narradas, no listadas. Usar conectores como "lo que sugiere", "esto es importante porque", "esto se traduce en", "esto confirma que".
8. Cierre como síntesis interpretativa, no como conclusión retórica. Nunca usar "en conclusión", "para cerrar", "en resumen".
9. Sin símbolos crudos como σ, %YoY, p.p. Si necesitas mencionar puntos porcentuales, escribir la palabra.
10. Sin adjetivos altisonantes ni metáforas. Vocabulario rico pero sobrio.

## Patrón típico de párrafo

Cada párrafo construye un argumento siguiendo este patrón flexible:

1. Identificación del indicador o fenómeno + qué mide.
2. Dato cuantitativo más reciente con magnitud y periodo.
3. Interpretación de qué significa ese dato en términos prácticos.
4. Conexión con otros datos o con la dinámica general.
5. Implicación opcional para diagnóstico de política.

Ejemplo del documento original:

"Uno de los indicadores más relevantes en este sentido es la Formación Bruta de Capital Fijo, que mide la inversión que realizan empresas y gobierno en maquinaria, equipo, plantas y construcción. Este indicador permite aproximar cuánto está ampliando la economía su capacidad futura de producción. Los datos más recientes muestran una caída anual de 3.6% en febrero. En términos prácticos, esto implica que la economía no sólo está creciendo poco hoy, sino que además está invirtiendo menos en su capacidad de crecimiento futuro."

## Vocabulario que el documento usa con naturalidad

- "Motores de demanda todavía activos"
- "Transmisión hacia producción nacional se está debilitando"
- "Preocupaciones estructurales relativamente estables"
- "Terreno expansivo / terreno de contracción"
- "Consolidación gradual de un entorno de bajo crecimiento"
- "Bajo dinamismo", "menor dinamismo"
- "Persistencia de estos factores"
- "Capacidad cada vez menor para impulsar producción"
- "Componentes más sensibles a expectativas"

## Vocabulario que se traduce o evita

| Término técnico | Versión usada en el documento |
|-----------------|-------------------------------|
| Tipo de cambio apreciado | "Peso relativamente apreciado frente al dólar" |
| TCRE / TCN bilateral | "Tipo de cambio fuerte" |
| Output gap | "Holgura en la economía, menor utilización de capacidad productiva" |
| PIB potencial | "Capacidad futura de producción" |
| Componente subyacente | "Componentes vinculados a alimentos y servicios" (cuando aplica) |
| Variación interanual | "Variación anual", "crecimiento anual", "caída anual" |
| Política monetaria contractiva | "Mayor peso a la actividad económica dentro del balance de riesgos" |
| Brecha del producto | "Menor presión sobre la demanda agregada" |
| EMOE | "Indicadores de confianza empresarial", "indicadores manufactureros" |
| IPM, IAT, ICE | "Pedidos manufactureros", "producción manufacturera" |
| ENCO | "Encuesta Nacional sobre Confianza del Consumidor" |
| FBCF | "Formación Bruta de Capital Fijo, que mide la inversión..." |
| IMCP | "Indicador Mensual del Consumo Privado, que mide el gasto..." |
| Spread de tasas | Evitar. Decir "diferencia entre tasas". |
| z-score, sigma | Evitar. Decir "movimiento poco usual / inusualmente fuerte". |

## Estructura de salida esperada (JSON)

```json
{
  "headline": "1 a 2 frases. Titular ejecutivo que la subsecretaria pueda usar como apertura en una reunión.",
  "parrafos": [
    "Párrafo 1: identificación del indicador, qué mide, dato más reciente, interpretación inmediata.",
    "Párrafo 2: comparación con periodos previos, conexión con otros datos del tablero.",
    "Párrafo 3 (opcional): contexto nacional o internacional si aplica."
  ],
  "diagnostico": "Párrafo de cierre. Síntesis interpretativa, no resumen. Qué implica este indicador para el diagnóstico general de la economía."
}
```

## Longitud objetivo

- headline: 25 a 50 palabras.
- Cada párrafo: 60 a 120 palabras.
- diagnostico: 40 a 80 palabras.
- Total interpretación: 250 a 450 palabras.

Más corto pierde sustancia. Más largo pierde foco ejecutivo.
