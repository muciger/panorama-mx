# Panorama MX · Contexto del proyecto

Tablero de indicadores económicos INEGI, en producción en https://muciger.github.io/panorama-mx/

## Audiencia y estilo de comunicación con Germán

Subsecretaria de Economía como destinataria final del tablero. NO es economista académica. Lenguaje plano, expandir acrónimos, métricas avanzadas detrás de toggle. Confirmado 2026-05-11.

Germán prefiere comunicación directa:

- Lenguaje claro y simple, voz activa siempre
- Usa "tú" y "tu" para dirigirse al lector
- Cada afirmación respaldada con evidencia específica
- Terminología técnica precisa sin definir conceptos básicos. Conocimiento experto en economía, política pública, banca de desarrollo y métodos cuantitativos
- Mezcla español e inglés natural. Español para conversación, inglés para contenido técnico
- Prosa estructurada para análisis complejos, tablas para comparaciones, evitar listas largas
- Borradores rápidos sobre perfección lenta
- Evitar guiones largos, hashtags, asteriscos, punto y coma
- Evitar metáforas, clichés, frases hechas, generalizaciones sin evidencia
- Evitar frases de cierre "en conclusión", "en resumen"
- Evitar markdown salvo cuando se solicite

## Arquitectura

Stack: Python 3.11 + Jinja2 + Chart.js + DuckDB (solo para IMSS). Sitio estático.

```
indicadores_inegi/
├── config/
│   ├── indicators.json          # catálogo de 32 indicadores
│   ├── calendar.json            # publicaciones ICS INEGI
│   ├── thresholds.json          # umbrales semáforo
│   ├── glossary.json            # 29 términos con definición
│   ├── glosario_traducido.json  # 16 acrónimos + 15 términos macro
│   ├── benchmarks.json
│   ├── eventos_macro.json
│   └── estilo_interpretacion.md # fuente de verdad del estilo writer
├── data/                        # JSONs normalizados de BIE-INEGI
├── docs/referencias/
│   └── imss_referencia_rediseño.html  # source del IMSS explorador
├── scripts/
│   ├── bie/ingest.py            # descarga BIE API
│   ├── calendar_sync.py         # parser ICS con stdlib
│   ├── normalize.py             # load_all + build_indicator
│   ├── composites.py            # 5 indicadores derivados
│   ├── tile_map.py              # paleta diverging mapas
│   ├── generate_interpretations.py  # writer DeepSeek + verifier Claude
│   ├── generate_synthesis.py    # síntesis macro (opcional)
│   ├── ingest_imss.py           # solo local, lee parquets 2.3GB
│   ├── build.py                 # render Jinja → site/
│   ├── validate.py              # auditoría calidad
│   └── refresh_daily.py         # orquesta todo
├── templates/
│   ├── base.html.j2             # sidebar + topbar
│   ├── index.html.j2
│   ├── indicador.html.j2
│   ├── reporte_semanal.html.j2
│   ├── reporte_semanal_completo.html.j2  # versión PDF
│   └── comparar.html.j2
├── assets/
│   ├── app.js                   # toggle avanzados + tooltips glosario
│   └── styles.css
└── site/                        # output, no committed... (sí está commiteado)
```

## Indicadores (32 totales)

31 que se generan como detalle individual en `site/indicador/<id>.html`. El indicador `empleo_imss` NO se genera ahí, vive como sección dedicada del sidebar en `site/imss_explorador.html` (HTML autocontenido de 1.7 MB con queries DuckDB embedidas).

## Pipeline writer + verifier

DeepSeek (deepseek-chat) escribe el draft, Claude Sonnet 4.6 verifica contra 4 reglas (precisión factual, anti-alucinación histórica, sin recomendación de política, estilo + glosario). Schema `auto_v2`: headline, parrafos[], diagnostico, draft_original, verificacion{}. 31 indicadores procesados, costo aproximado 0.20 USD por corrida completa.

Estilo de referencia: docs/referencias/Seguimiento de coyuntura económica 080526_V2.docx (análisis narrativo macro tipo ensayo, 1500 palabras, conecta múltiples indicadores bajo una tesis). El usuario adjuntó este docx como referencia de estilo objetivo para futuras iteraciones (no implementado todavía).

## Comandos clave

```bash
# Pipeline completo (descarga datos, regenera todo)
python3 scripts/refresh_daily.py

# Sin BIE refresh (modo cloud, usa data existente)
python3 scripts/refresh_daily.py --skip-bie --skip-interp --skip-calendar

# Build sin tocar datos
python3 scripts/build.py

# Regenerar interpretaciones forzando todas (~0.20 USD)
python3 scripts/generate_interpretations.py --force

# Ingest IMSS especial (solo local, requiere parquets en Mac)
python3 scripts/ingest_imss.py

# Validate (audita calidad, no bloquea)
python3 scripts/validate.py

# Servir local para probar
cd site/ && python3 -m http.server 8765
# Abrir http://127.0.0.1:8765/
```

## Deploy GitHub Actions

Repo: `github.com/muciger/panorama-mx` (privado). Hosting GitHub Pages en branch `gh-pages`.

**Arquitectura skip-bie permanente** (importante).

El workflow `deploy.yml` NO descarga BIE en cloud porque INEGI parece geo-bloquear IPs no mexicanas. Devuelve responses parciales/vacías sin error 4xx. En sesión 2026-05-11 el workflow destruyó 112,652 líneas de data buena cuando intentó refrescar BIE desde IP USA. Recuperado con `git checkout` del commit anterior.

Workflow ahora:
- Corre solo on-push o manual
- Usa `python3 scripts/refresh_daily.py --skip-bie --skip-interp --skip-calendar`
- Tiene sanity check que aborta si algún `data/*.json` perdió >50% líneas vs commit anterior
- Solo regenera HTML y deploya a gh-pages

Workflow `imss_reminder.yml` abre issue automático día 12 de cada mes a las 10:00 CST para recordar correr `ingest_imss.py` localmente.

Flujo operativo:

```bash
# 1. Refrescar datos diariamente desde Mac (IP mexicana)
python3 scripts/refresh_daily.py
git add data/ config/calendar.json
git commit -m "data: refresh $(date +%Y-%m-%d)"
git push
# El workflow auto-deploya el sitio a Pages

# 2. Refresh IMSS mensual cuando llegue el issue automático
python3 scripts/ingest_imss.py
git add data/empleo_imss.json docs/referencias/imss_referencia_rediseño.html
git commit -m "imss: refresh mensual"
git push
```

Secrets configurados en GitHub: INEGI_BIE_TOKEN (no se usa en cloud por skip-bie), DEEPSEEK_API_KEY, ANTHROPIC_API_KEY.

## Features del tablero

**Onboarding ligero** (Frente 2 completado):

1. Tooltips de glosario. Subrayado punteado naranja en acrónimos (MA12, FBCF, IGAE, INPP, ICC, EMOE, subyacente, var anual, z-score, etc.). 29 términos en `config/glossary.json`. Implementación: `v3InitGlossary()` en `assets/app.js` con TreeWalker. CSS `::after` con `attr(data-glo)` para tooltip flotante.

2. Toggle "Datos avanzados" en topbar (icono gráfico + ON/OFF). Persiste en localStorage `panorama-show-advanced`. Default OFF. Elementos `.advanced` ocultos: outlier-badge z-score, fila desv estándar + p25/p75, cards record-percentil y record-zscore, columna MA12 en tabla mensual.

3. Navegación coherente entre las 3 secciones (Inicio, Reporte semanal en estilo warm editorial, IMSS explorador con paleta alineada al sitio).

**Reporte semanal PDF v4** (validado):

3 páginas A4. Sin síntesis ejecutiva, sin tabla próximas, sin footer "Panorama MX". 11 indicadores con headline + diagnóstico + tiles + chart. Dedup de indicadores vinculados via campo `vinculado_con` en config/indicators.json (ej. inflacion_resumen se suprime cuando inpc_mensual está en la ventana).

Ventana del reporte: rolling lunes a hoy. Si hoy es lun/mar, retrocede al lunes anterior (cubre semana laboral terminada). Si es mie a dom, usa lunes en curso.

## Estado al 2026-05-11

| Componente | Estado |
|---|---|
| Repo main local + GitHub | datos buenos restaurados |
| Site producción gh-pages | mostrando datos vacíos del último deploy malo, pendiente re-deploy con skip-bie |
| Workflow deploy.yml | actualizado a skip-bie permanente con sanity check, sin commitear todavía |
| Workflow imss_reminder.yml | active |
| Onboarding tooltips + toggle avanzados | completado |
| PDF semanal v4 | validado |
| Memoria Cowork | en `/Users/germanmucino/Library/Application Support/Claude/local-agent-mode-sessions/.../memory/` |

## Pendientes inmediatos

1. Commitear y pushear los cambios al workflow (deploy.yml + SETUP.md actualizado en sesión actual).
2. Re-habilitar workflow con `gh workflow enable deploy.yml`.
3. Disparar manualmente para regenerar gh-pages con datos buenos.
4. Confirmar en navegador que los 5 KPI hero (INFLACIÓN GENERAL, ACTIVIDAD ECONÓMICA, SALDO BALANZA, CONFIANZA, DESOCUPACIÓN) muestran datos completos.

Comandos para ejecutar:

```bash
cd "/Users/germanmucino/Desktop/Descargas firefox/INEGI interactivo/Interactivo indicadores INEGI/indicadores_inegi"
git add .github/
git commit -m "feat: workflow skip-bie permanente + sanity check de tamaños"
gh workflow enable deploy.yml
git push
gh run watch
```

## Pendientes futuros

1. **Frente 3 contexto macro nacional/internacional**: pipeline `scripts/contexto/` con Banxico SIE + FRED. Chips con tasa Banxico, USD/MXN, Fed funds, US CPI, peers LATAM, Brent. Inyectar al prompt del writer.

2. **Cobertura glosario en reporte semanal y comparar**: los selectores actuales de `v3InitGlossary()` no cubren clases editoriales de esas páginas. Ampliar selectores en `assets/app.js`.

3. **Investigar root cause del BIE geo-block**: probar curl desde otra IP cloud (Cloudflare Workers, Render, etc.) contra el endpoint BIE para confirmar/descartar geo-block. Si no es geo-block, podemos volver a automatizar el ingest en cloud.

4. **Estilo narrativo macro tipo "Seguimiento de coyuntura"**: armar bloque "Lectura de la semana" en el PDF que sintetice los 11 indicadores en 2-3 párrafos narrativos macro, replicando el docx adjunto por el usuario.

5. **Migración Node.js 24**: cuando llegue septiembre 2026, actualizar actions/checkout, actions/setup-python, peaceiris/actions-gh-pages a sus versiones compatibles con Node 24.

6. **Dominio propio opcional**: tipo `panorama.tudominio.mx` vía Cloudflare/Namecheap CNAME.

## Configuración local del usuario

- Mac: `~/Desktop/Descargas firefox/INEGI interactivo/Interactivo indicadores INEGI/indicadores_inegi`
- Parquets IMSS: `~/Desktop/Descargas firefox/Datos empleo IMSS/Datos empleo imss/datos/imss_parquet/` (88 parquets, 2.3 GB, ene-2019 a abr-2026)
- `.env` con INEGI_BIE_TOKEN, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY
- gh CLI ya autenticado con scope workflow
- Repo remote: https://github.com/muciger/panorama-mx.git

## Lecciones operativas

- **Nunca dejar que cloud sobrescriba data sin sanity check**. Workflow ahora tiene check de >50% reducción de líneas.
- **El BIE no es confiable desde cloud**. Geo-block o similar. Datos se actualizan desde Mac.
- **Validate es auditoría, no bloqueante**. Se marcó `optional=True` en refresh_daily.py para no romper deploy.
- **GitHub auto-disabled workflows después de fallos consecutivos**. Re-habilitar con `gh workflow enable <name>`.
- **Captura stderr completo en subprocess para debug cloud**. El truncado a 500 chars ocultó el root cause inicialmente.
