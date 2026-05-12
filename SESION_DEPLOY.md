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

El sitio **se actualiza solo** todos los días a las **8:30 AM hora México**.

### Qué hace:
1. Descarga datos frescos del INEGI/IMSS via API
2. Genera interpretaciones con IA
3. Corre `python3 scripts/refresh_daily.py`
4. Publica `site/` en la rama `gh-pages`

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
# el workflow diario actualiza el sitio solo
```

### Ver cambios de inmediato:
Ir a GitHub → Actions → Run workflow (manual)

### Build local para pruebas:
```bash
python3 scripts/build.py
# abre site/index.html en el navegador
```
