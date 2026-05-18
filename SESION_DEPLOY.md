# Sesión de deploy — panorama-mx
**Fecha:** 7 de mayo de 2026

---

## Lo que teníamos al inicio
- Proyecto `indicadores_inegi` completo en local (131 archivos)
- Repo git inicializado, archivos en staging
- Sin remote de GitHub, sin rama `gh-pages`

---

## Lo que hicimos

### 1. Primer commit
```bash
git commit -m "Initial commit: INEGI indicadores dashboard"
```
- **Resultado:** commit `8a190a9` en `main`, 131 archivos confirmados

---

### 2. Crear repo en GitHub y push
```bash
gh repo create panorama-mx --public \
  --description "Dashboard de indicadores económicos de México (INEGI/IMSS)" \
  --source . --remote origin --push
```
- Repo público en **https://github.com/muciger/panorama-mx**
- Rama `main` pusheada con todo el código fuente

---

### 3. Generar el sitio estático
`site/` está en `.gitignore` (se regenera en cada build). La generamos localmente:
```bash
pip3 install jinja2
python3 scripts/build.py
```
- **Resultado:** 32 páginas HTML generadas en `site/`

---

### 4. Crear y pushear rama `gh-pages`
```bash
git checkout --orphan gh-pages
git rm -rf . --quiet
# copiar solo contenido de site/ al root
git add .
git commit -m "Initial GitHub Pages deploy"
git push origin gh-pages
git checkout main
```
- Rama `gh-pages` con 144 archivos (HTML + CSS + JS + CSV de datos)

---

### 5. Habilitar GitHub Pages
```bash
gh api repos/muciger/panorama-mx/pages \
  --method POST \
  -f "source[branch]=gh-pages" \
  -f "source[path]=/"
```
- **Sitio publicado en:** https://muciker.github.io/panorama-mx/

---

## Estructura del repo

```
panorama-mx/
├── main              ← código fuente (scripts, templates, config, data)
└── gh-pages          ← sitio estático publicado (generado por workflow)
```

---

## Workflow CI/CD (.github/workflows/deploy.yml)

El workflow corre **on-push a main** y por **disparo manual** (no en cron).

### Qué hace (arquitectura skip-bie permanente):
1. **NO descarga del BIE en cloud.** La API INEGI geo-bloquea IPs no
   mexicanas devolviendo HTTP 200 con cuerpo vacío. En 2026-05-11 un run
   cloud destruyó 112,652 líneas de datos buenos por esto.
2. Los datos se actualizan **localmente desde la Mac** (IP mexicana) y se
   commitean a `main`.
3. El workflow corre `refresh_daily.py --skip-bie --skip-interp --skip-calendar`
   (solo composites + build + validate sobre los `data/` del repo).
4. Sanity check (`scripts/ci_sanity_check.py`) aborta el deploy si algún
   `data/*.json` perdió >50% de registros vs el commit anterior.
5. Publica `site/` en la rama `gh-pages` (conservando historial para rollback).

> No reactivar la descarga BIE en cloud sin antes resolver el geo-block.

### Disparar manualmente:
GitHub → Actions → *Panorama MX — Build & Deploy* → **Run workflow**

### Monitorear:
GitHub → pestaña **Actions** → ver ✅ o ❌ con logs

---

## Secrets necesarios para el workflow

Configurar en: **Settings → Secrets and variables → Actions**

| Secret | Uso |
|--------|-----|
| `INEGI_BIE_TOKEN` | API del Banco de Información Económica (INEGI) |
| `DEEPSEEK_API_KEY` | Generación de interpretaciones con IA |
| `ANTHROPIC_API_KEY` | Alternativa Claude para interpretaciones |

> Sin los secrets el workflow falla, pero el sitio actual sigue disponible.

---

## Flujo para cambios futuros

### Cambio de código/config:
```bash
git add .
git commit -m "descripción"
git push origin main
# el push a main dispara el workflow y republica el sitio
```

### Ver cambios de inmediato:
Ir a GitHub → Actions → Run workflow (manual)

### Build local para pruebas:
```bash
python3 scripts/build.py
# abre site/index.html en el navegador
```
