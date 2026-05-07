# Base de datos IMSS — Empleo formal 2019–2026

## Estructura de archivos

```
Datos empleo imss/
├── imss_parquet/          87 archivos .parquet, uno por mes (ene 2019 – mar 2026)
├── catalogos.xlsx         Catálogos de todas las dimensiones
└── IMSS_empleo_guia.md    Este archivo
```

## Conexión básica

```python
import duckdb
import pandas as pd

con = duckdb.connect()
PARQUET = 'imss_parquet/*.parquet'   # ajusta la ruta si es necesario
```

---

## Dimensiones y métricas

### Métricas (columnas numéricas)

| Columna | Descripción |
|---|---|
| `ta` | Puestos de trabajo afiliados al IMSS (empleo formal total) |
| `teu` | Eventuales urbanos |
| `tec` | Eventuales del campo |
| `tpu` | Permanentes urbanos |
| `tpc` | Permanentes del campo |
| `asegurados` | Total asegurados (incluye sin empleo asociado: modalidades 32, 33, 40) |
| `no_trabajadores` | Asegurados sin empleo asociado |
| `ta_sal` | Puestos de trabajo con salario reportado |
| `masa_sal_ta` | Masa salarial total |
| `teu_sal`, `tec_sal`, `tpu_sal`, `tpc_sal` | Puestos con salario por categoría |

> **Nota clave:** Para análisis de empleo formal usa `ta`, no `asegurados`. `asegurados` incluye personas aseguradas sin un empleo (seguro familiar, facultativo, etc.).

> **Salario base de cotización diario:** `masa_sal_ta / ta_sal` (promedio ponderado, en pesos).

### Dimensiones

| Columna | Tipo | Catálogo | Notas |
|---|---|---|---|
| `fecha` | date | — | Último día de cada mes |
| `cve_entidad` | Int16 | `entidades` | 1–32, estándar IMSS |
| `cve_municipio` | category | `municipios` | Clave alfanumérica IMSS |
| `sector_economico_1` | Int8 | `sector_1` | 9 divisiones (0,1,3,4,5,6,7,8,9) |
| `sector_economico_2` | Int8 | `sector_2` | 62 grupos |
| `sector_economico_4` | Int16 | `sector_4` | 276 fracciones |
| `tamaño_patron` | category | `tamaño_patron` | S1–S7, None=No aplica |
| `sexo` | Int8 | `sexo` | 1=Hombre, 2=Mujer, 3=No binario |
| `rango_edad` | category | `rango_edad` | E1–E14, ND=No disponible |
| `rango_salarial` | category | `rango_salarial` | W1–W25, None=No aplica |

---

## Catálogos

```python
xl = pd.ExcelFile('catalogos.xlsx')

entidades  = pd.read_excel(xl, 'entidades')   # cve_entidad_num, desc_entidad
sectores1  = pd.read_excel(xl, 'sector_1')    # sector_economico_1, desc_sector1
sectores2  = pd.read_excel(xl, 'sector_2')    # sector_economico_2, desc_sector2
sectores4  = pd.read_excel(xl, 'sector_4')    # sector_economico_4, desc_sector4
tamanos    = pd.read_excel(xl, 'tamaño_patron') # tamaño_patron, desc_tamaño
sexos      = pd.read_excel(xl, 'sexo')        # sexo, desc_sexo
edades     = pd.read_excel(xl, 'rango_edad')  # rango_edad, desc_edad
salarios   = pd.read_excel(xl, 'rango_salarial') # rango_salarial, desc_salarial
municipios = pd.read_excel(xl, 'municipios')  # cve_municipio, desc_municipio, cve_entidad_num
```

---

## Queries frecuentes

### Serie nacional mensual

```python
df = con.execute(f"""
    SELECT
        strftime(fecha, '%Y-%m') AS mes,
        SUM(ta)  AS ta,
        SUM(teu) AS teu,
        SUM(tec) AS tec,
        SUM(tpu) AS tpu,
        SUM(tpc) AS tpc
    FROM '{PARQUET}'
    GROUP BY 1
    ORDER BY 1
""").df()
```

### Por entidad, último mes disponible

```python
df = con.execute(f"""
    SELECT
        cve_entidad,
        SUM(ta) AS ta
    FROM '{PARQUET}'
    WHERE fecha = (SELECT MAX(fecha) FROM '{PARQUET}')
    GROUP BY 1
    ORDER BY 2 DESC
""").df()

# Unir etiqueta
df = df.merge(entidades[['cve_entidad_num','desc_entidad']],
              left_on='cve_entidad', right_on='cve_entidad_num')
```

### Variación interanual por entidad

```python
df = con.execute(f"""
    WITH base AS (
        SELECT
            strftime(fecha, '%Y-%m') AS mes,
            cve_entidad,
            SUM(ta) AS ta
        FROM '{PARQUET}'
        GROUP BY 1, 2
    )
    SELECT
        a.mes,
        a.cve_entidad,
        a.ta,
        b.ta AS ta_hace_12m,
        ROUND((a.ta - b.ta) * 100.0 / b.ta, 2) AS var_pct
    FROM base a
    JOIN base b
        ON a.cve_entidad = b.cve_entidad
        AND strftime(a.mes::DATE - INTERVAL 12 MONTH, '%Y-%m') = b.mes
    ORDER BY 1, 2
""").df()
```

### Por sector económico (división, nivel 1)

```python
df = con.execute(f"""
    SELECT
        strftime(fecha, '%Y-%m') AS mes,
        sector_economico_1,
        SUM(ta) AS ta
    FROM '{PARQUET}'
    WHERE sector_economico_1 IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
""").df()

df = df.merge(sectores1, on='sector_economico_1')
```

### Salario base de cotización promedio por sector

```python
df = con.execute(f"""
    SELECT
        strftime(fecha, '%Y-%m') AS mes,
        sector_economico_1,
        SUM(masa_sal_ta) / NULLIF(SUM(ta_sal), 0) AS salario_diario_promedio
    FROM '{PARQUET}'
    WHERE sector_economico_1 IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
""").df()
```

### Brecha de género (hombres vs mujeres)

```python
df = con.execute(f"""
    SELECT
        strftime(fecha, '%Y-%m') AS mes,
        sexo,
        SUM(ta) AS ta
    FROM '{PARQUET}'
    WHERE sexo IN (1, 2)
    GROUP BY 1, 2
    ORDER BY 1, 2
""").df()

# Pivot
df_wide = df.pivot(index='mes', columns='sexo', values='ta')
df_wide.columns = ['hombres', 'mujeres']
df_wide['pct_mujeres'] = df_wide['mujeres'] / (df_wide['hombres'] + df_wide['mujeres'])
```

### Por rango salarial, nivel nacional, último mes

```python
df = con.execute(f"""
    SELECT
        rango_salarial,
        SUM(ta) AS ta
    FROM '{PARQUET}'
    WHERE fecha = (SELECT MAX(fecha) FROM '{PARQUET}')
      AND rango_salarial IS NOT NULL
    GROUP BY 1
    ORDER BY 1
""").df()

df = df.merge(salarios, on='rango_salarial')
```

### Filtrar por estado y sector específico

```python
# Ejemplo: manufactura (sector 3) en Nuevo León (entidad 19)
df = con.execute(f"""
    SELECT
        strftime(fecha, '%Y-%m') AS mes,
        SUM(ta) AS ta,
        SUM(tpu) AS permanentes_urbanos
    FROM '{PARQUET}'
    WHERE cve_entidad = 19
      AND sector_economico_1 = 3
    GROUP BY 1
    ORDER BY 1
""").df()
```

---

## Visualización rápida con matplotlib

```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Serie nacional de ta
df_nac = con.execute(f"""
    SELECT strftime(fecha, '%Y-%m') AS mes, SUM(ta) AS ta
    FROM '{PARQUET}' GROUP BY 1 ORDER BY 1
""").df()

fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(df_nac['mes'], df_nac['ta'] / 1e6, linewidth=2, color='#1a6496')
ax.set_title('Empleo formal IMSS — Total nacional')
ax.set_ylabel('Millones de puestos')
ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:.1f}M'))
ax.set_xticks(range(0, len(df_nac), 6))
ax.set_xticklabels(df_nac['mes'].iloc[::6], rotation=45, ha='right')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.show()
```

---

## Notas metodológicas (fuente: IMSS)

- Los archivos son snapshot del último día de cada mes, no flujos.
- Un asegurado con múltiples modalidades se cuenta una vez por modalidad.
- `tamaño_patron` no aplica a modalidades 32, 33, 40, 34, 43 y 44.
- `rango_salarial` no aplica a modalidades sin empleo asociado (32, 33, 40). Las modalidades 30, 35, 43 y 44 usan salario de referencia igual al mínimo y se contabilizan en W1.
- El salario base de cotización tiene tope máximo de 25 veces la UMA (antes de feb 2017: 25 veces el salario mínimo).
- `sector_economico_1` sigue la clasificación del Reglamento de la LSS (Art. 196). El código 3 corresponde a Industrias de la Transformación; los códigos 2 y 3 agrupan la misma división pero en los datos solo aparece el código 3.
- A partir de 2017 se reporta `rango_edad` para modalidad 32; antes aparecía como ND.

---

*Fuente: IMSS Datos Abiertos — datos.imss.gob.mx | Procesado con DuckDB 1.5 | Actualizado abril 2026*
