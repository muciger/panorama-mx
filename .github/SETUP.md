# Setup GitHub Actions · Panorama MX

Guía de configuración paso a paso para automatizar el refresh diario del tablero.

## Paso 1. Crear repositorio en GitHub

Abre https://github.com/new

- Nombre: `panorama-mx` (o el que prefieras)
- Visibilidad: Private (recomendado, porque el repo contiene tu pipeline)
- No marques "Add a README" ni licencia

## Paso 2. Subir el proyecto

En tu Mac, abre Terminal y corre:

```bash
cd "/Users/germanmucino/Desktop/Descargas firefox/INEGI interactivo/Interactivo indicadores INEGI/indicadores_inegi"

git init -b main
git add .
git commit -m "init: tablero Panorama MX"
git remote add origin https://github.com/TU_USUARIO/panorama-mx.git
git push -u origin main
```

Reemplaza `TU_USUARIO` por tu handle de GitHub.

## Paso 3. Configurar secrets

En el repo de GitHub, ve a `Settings → Secrets and variables → Actions → New repository secret`. Crea tres secrets:

| Nombre | Valor |
|--------|-------|
| `INEGI_BIE_TOKEN` | Tu token del API BIE-INEGI |
| `DEEPSEEK_API_KEY` | Tu API key de DeepSeek |
| `ANTHROPIC_API_KEY` | Tu API key de Anthropic (para verifier) |

Estos valores los tienes en tu `.env` local. NO los subas al repo, viven solo en secrets.

## Paso 4. Habilitar GitHub Pages

En el repo, ve a `Settings → Pages`:

- Source: `Deploy from a branch`
- Branch: `gh-pages` (se creará automáticamente en la primera corrida)
- Folder: `/ (root)`

Guarda. La primera corrida del workflow creará la rama.

## Paso 5. Disparar el primer build manualmente

Ve a `Actions → Panorama MX — Build & Deploy → Run workflow`. Selecciona main y dale a Run.

Espera ~5-10 minutos. Cuando termine en verde, abre:

```
https://TU_USUARIO.github.io/panorama-mx/
```

Ahí está tu tablero.

## Cómo funciona el cron

| Workflow | Frecuencia | Hora | Acción |
|----------|-----------|------|--------|
| deploy.yml | Diario | 13:00 UTC = 7:00 CST | Refresca BIE, calendario, interpretaciones, build, deploy |
| imss_reminder.yml | Mensual día 12 | 16:00 UTC = 10:00 CST | Abre un issue recordando correr ingest_imss local |

INEGI publica boletines a las 6:00 AM hora centro. El refresh corre a las 7:00 AM para dar 1 hora de margen.

Si haces cambios en `templates/`, `assets/`, `scripts/` o `config/` y haces push, el deploy también se dispara automáticamente.

## Costo

Gratis. GitHub Actions da 2000 minutos/mes para repos privados. Cada corrida toma ~3-5 minutos, así que sobran ~1700 minutos al mes.

APIs externas:
- INEGI BIE: gratis (token gubernamental)
- DeepSeek: ~0.05 USD por corrida del writer (31 indicadores)
- Anthropic: ~0.15 USD por corrida del verifier
- Costo mensual estimado: 6 USD si corre diario

## Actualizar IMSS mensual desde Mac

Los parquets IMSS pesan 2.3 GB y no caben en GitHub gratis. El flujo es:

1. Cada mes IMSS publica datos del mes anterior (aprox día 10-12)
2. GitHub abre un issue automático el día 12 a las 10:00 CST recordándotelo
3. Tú descargas el parquet nuevo del mes desde https://datos.imss.gob.mx/
4. Lo guardas en `~/Desktop/Descargas firefox/Datos empleo IMSS/Datos empleo imss/datos/imss_parquet/`
5. Corres en Terminal:

```bash
cd "/Users/germanmucino/Desktop/Descargas firefox/INEGI interactivo/Interactivo indicadores INEGI/indicadores_inegi"
python3 scripts/ingest_imss.py
git add data/empleo_imss.json docs/referencias/imss_referencia_rediseño.html
git commit -m "imss: refresh mensual"
git push
```

El push dispara automáticamente el workflow `deploy.yml` y el sitio se actualiza con los datos IMSS nuevos.

## Troubleshooting

**El workflow falla con "DEEPSEEK_API_KEY faltante".** Falta agregar el secret. Ve al paso 3.

**El sitio en Pages está vacío o muestra 404.** El primer deploy tarda 1-2 minutos en propagarse. Revisa Settings → Pages para confirmar que la rama es `gh-pages`.

**El workflow corre pero los datos no se actualizan.** Revisa el log del paso "Correr pipeline completo". Si INEGI no publicó nada nuevo ese día, el data no cambia. El sitio se redesplega pero con los mismos datos.

**Quiero un dominio propio.** En Settings → Pages → Custom domain. Ej. `tablero.tudominio.mx`. Compras el dominio en Cloudflare o Namecheap, apuntas el CNAME a `TU_USUARIO.github.io`.

**No quiero que el sitio sea público.** GitHub Pages en repos privados requiere plan GitHub Pro (4 USD/mes) o un workaround: hosting privado en Cloudflare Pages o Vercel con auth básico.

## Cómo detener la automatización

`Actions → Panorama MX — Build & Deploy → ··· → Disable workflow`. El workflow no correrá hasta que lo vuelvas a habilitar. No borra nada existente, solo pausa.
