"""Normaliza data/<id>.json crudo al shape UI-ready que esperan los templates y el mockup.

Se usa desde scripts/build.py (pipeline real) y desde populate_mockup.py (mockup temporal).
Mantener ambos consumidores del mismo helper evita drift entre los dos outputs.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

# ── Metodología por indicador (extraída de los comunicados de prensa) ──────────
METODOLOGIA_MAP = {
    "igae": {
        "titulo": "Indicador Global de la Actividad Económica (IGAE)",
        "antecedentes": "Permite conocer y dar seguimiento a la evolución del sector real de la economía en el corto plazo. Disponible desde enero de 1993. Expresado en índices de volumen físico tipo Laspeyres, base 2018. Representatividad de 94.8% del Valor Agregado Bruto de 2018.",
        "periodicidad": "Mensual. Se publica 53 días naturales después de concluido el mes de referencia.",
        "cobertura": "Nacional.",
        "fuentes": "EMIM, ENEC, EMEC, EMS, EIMM, ENOE, índices nacionales de precios y registros administrativos.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Ficha metodológica (BIE)", "url": "https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=702825099060"},
            {"label": "Programa IGAE 2018", "url": "https://www.inegi.org.mx/programas/igae/2018/"},
        ],
    },
    "igae_ioae_resumen": {
        "titulo": "Indicador Global de la Actividad Económica (IGAE)",
        "antecedentes": "Permite conocer y dar seguimiento a la evolución del sector real de la economía en el corto plazo. Disponible desde enero de 1993. Expresado en índices de volumen físico tipo Laspeyres, base 2018.",
        "periodicidad": "Mensual.",
        "cobertura": "Nacional.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Ficha metodológica (BIE)", "url": "https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=702825099060"},
            {"label": "Programa IGAE 2018", "url": "https://www.inegi.org.mx/programas/igae/2018/"},
        ],
    },
    "enoe_trimestral": {
        "titulo": "Encuesta Nacional de Ocupación y Empleo (ENOE) — Resultados trimestrales",
        "antecedentes": "Principal fuente de información sobre el mercado laboral mexicano. Inició levantamiento en enero de 2005. Ofrece datos de fuerza de trabajo, ocupación, informalidad laboral, subocupación y desocupación.",
        "periodicidad": "Trimestral. Publica en días establecidos en el Calendario de Difusión del INEGI.",
        "cobertura": "Nacional, cuatro tamaños de localidad, 32 entidades federativas y 39 ciudades autorrepresentadas.",
        "muestreo": "Probabilístico, bietápico, estratificado y por conglomerados. Panel rotatorio de 5 paneles; cada uno permanece 5 trimestres. Tamaño de muestra: ~150 mil viviendas por trimestre.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Ficha metodológica (BIE)", "url": "https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=702825099060"},
            {"label": "Programa ENOE 15 años y más", "url": "https://www.inegi.org.mx/programas/enoe/15ymas/"},
            {"label": "Tabulados ENOE", "url": "https://www.inegi.org.mx/programas/enoe/15ymas/#Tabulados"},
            {"label": "STPS — Centro de información", "url": "https://www.gob.mx/stps"},
        ],
    },
    "enoe_mensual": {
        "titulo": "Encuesta Nacional de Ocupación y Empleo (ENOE) — Indicadores mensuales",
        "antecedentes": "Principal fuente de información sobre el mercado laboral mexicano. Ofrece datos mensuales de PEA, ocupación, informalidad, subocupación y desocupación.",
        "periodicidad": "Mensual.",
        "cobertura": "Nacional, áreas más y menos urbanizadas, 32 entidades federativas y 39 ciudades autorrepresentadas.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Ficha metodológica (BIE)", "url": "https://www.inegi.org.mx/app/biblioteca/ficha.html?upc=702825099060"},
            {"label": "Programa ENOE 15 años y más", "url": "https://www.inegi.org.mx/programas/enoe/15ymas/"},
            {"label": "Tabulados ENOE", "url": "https://www.inegi.org.mx/programas/enoe/15ymas/#Tabulados"},
        ],
    },
    # ── Macro ─────────────────────────────────────────────────────────────────
    "pib_anual": {
        "titulo": "Producto Interno Bruto (PIB) — Variación real anual",
        "antecedentes": "Visión oportuna y con periodicidad trimestral sobre la situación económica del país, consistente con las cuentas nacionales anuales. Disponible desde 1980. Índices de volumen físico tipo Laspeyres, base 2018. Representatividad: 749 clases de actividad SCIAN 2018.",
        "periodicidad": "Trimestral. Se publica en promedio 53 días después de concluido el trimestre de referencia.",
        "cobertura": "Nacional.",
        "fuentes": "EMIM, ENEC, EMEC, EMS, ENOE, índices nacionales de precios, registros administrativos y estadísticas del sector externo.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa PIB trimestral 2018", "url": "https://www.inegi.org.mx/programas/pib/2018/"},
            {"label": "BIE — Cuentas Nacionales", "url": "https://www.inegi.org.mx/sistemas/bie/"},
        ],
    },
    "pib_trimestral": {
        "titulo": "Producto Interno Bruto (PIB) — Variación trimestral y anual",
        "antecedentes": "Visión oportuna y con periodicidad trimestral sobre la situación económica del país. Disponible desde 1980. Índices de volumen físico tipo Laspeyres, base 2018.",
        "periodicidad": "Trimestral. Se publica en promedio 53 días después de concluido el trimestre de referencia.",
        "cobertura": "Nacional.",
        "fuentes": "EMIM, ENEC, EMEC, EMS, ENOE, índices nacionales de precios, registros administrativos y estadísticas del sector externo.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa PIB trimestral 2018", "url": "https://www.inegi.org.mx/programas/pib/2018/"},
            {"label": "BIE — Cuentas Nacionales", "url": "https://www.inegi.org.mx/sistemas/bie/"},
        ],
    },
    "pib_por_actividad": {
        "titulo": "Producto Interno Bruto (PIB) por actividad económica",
        "antecedentes": "Desagregación trimestral del PIB por grandes grupos de actividad: primarias, secundarias y terciarias, con apertura a nivel subsector SCIAN 2018. Base 2018.",
        "periodicidad": "Trimestral. Se publica en promedio 53 días después de concluido el trimestre de referencia.",
        "cobertura": "Nacional.",
        "fuentes": "EMIM, ENEC, EMEC, EMS, ENOE, índices nacionales de precios, registros administrativos.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa PIB trimestral 2018", "url": "https://www.inegi.org.mx/programas/pib/2018/"},
        ],
    },
    # ── Precios ───────────────────────────────────────────────────────────────
    "inflacion_resumen": {
        "titulo": "Índice Nacional de Precios al Consumidor (INPC) — Resumen inflación",
        "antecedentes": "Mide la variación de los precios de una canasta de bienes y servicios representativa del consumo de los hogares mexicanos. Base 2Q julio 2018=100. Disponible desde enero de 1969.",
        "periodicidad": "Quincenal y mensual. Se publica los días 10 y 25 de cada mes en el DOF, o el día hábil anterior.",
        "cobertura": "Nacional y por ciudades.",
        "fuentes": "Encuestadores de campo en establecimientos y mercados de 55 ciudades del país.",
        "ajuste": "No aplica ajuste estacional al índice de precios.",
        "links": [
            {"label": "Programa INPC 2018", "url": "https://www.inegi.org.mx/programas/inpc/2018/"},
            {"label": "BIE — Precios e inflación", "url": "https://www.inegi.org.mx/sistemas/bie/"},
        ],
    },
    "inpc_mensual": {
        "titulo": "Índice Nacional de Precios al Consumidor (INPC) — Serie mensual",
        "antecedentes": "Mide la variación de los precios de una canasta de bienes y servicios representativa del consumo de los hogares mexicanos. Base 2Q julio 2018=100. Disponible desde enero de 1969.",
        "periodicidad": "Mensual. Se publica el día 10 del mes siguiente en el DOF, o el día hábil anterior.",
        "cobertura": "Nacional y por ciudades.",
        "fuentes": "Encuestadores de campo en establecimientos y mercados de 55 ciudades del país.",
        "ajuste": "No aplica ajuste estacional al índice de precios.",
        "links": [
            {"label": "Programa INPC 2018", "url": "https://www.inegi.org.mx/programas/inpc/2018/"},
        ],
    },
    "inpc_quincenal": {
        "titulo": "Índice Nacional de Precios al Consumidor (INPC) — Serie quincenal",
        "antecedentes": "Mide la variación de los precios de una canasta representativa. Publicación quincenal. Base 2Q julio 2018=100.",
        "periodicidad": "Quincenal. Primera quincena el día 25 del mismo mes; segunda el día 10 del mes siguiente.",
        "cobertura": "Nacional y por ciudades.",
        "fuentes": "Encuestadores de campo en establecimientos y mercados de 55 ciudades del país.",
        "ajuste": "No aplica ajuste estacional al índice de precios.",
        "links": [
            {"label": "Programa INPC 2018", "url": "https://www.inegi.org.mx/programas/inpc/2018/"},
        ],
    },
    "inpp": {
        "titulo": "Índice Nacional de Precios Productor (INPP)",
        "antecedentes": "Mide la variación de precios de bienes y servicios en la primera etapa de comercialización (productor). Disponible desde enero de 1980. Base julio 2019=100. Se publica por el lado de la oferta (por origen) y por el lado de la demanda (por destino).",
        "periodicidad": "Mensual. Se publica en la misma fecha que el INPC.",
        "cobertura": "Nacional.",
        "fuentes": "Encuestadores de campo, registros administrativos e información de organismos sectoriales.",
        "ajuste": "No aplica ajuste estacional.",
        "links": [
            {"label": "Programa INPP 2018", "url": "https://www.inegi.org.mx/programas/inpp/2018/"},
        ],
    },
    # ── Actividad ─────────────────────────────────────────────────────────────
    "actividad_industrial": {
        "titulo": "Indicador Mensual de la Actividad Industrial (IMAI)",
        "antecedentes": "Mide la evolución mensual de la producción de los sectores minería, energía, construcción y manufacturas. Disponible desde enero de 1993. Índices de volumen físico base 2018.",
        "periodicidad": "Mensual. Se publica 42 días naturales después de concluido el mes de referencia.",
        "cobertura": "Nacional.",
        "fuentes": "SCNM: EMIM, ENEC, ENOE, registros administrativos de Pemex, CNH y CFE.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa IMAI 2018", "url": "https://www.inegi.org.mx/programas/imai/2018/"},
        ],
    },
    "consumo_privado": {
        "titulo": "Indicador Mensual del Consumo Privado (IMCP)",
        "antecedentes": "Mide la evolución mensual del consumo de los hogares en bienes y servicios. Disponible desde enero de 1993. Índices de volumen físico base 2018. Representatividad del SCNM.",
        "periodicidad": "Mensual. Se publica los primeros días de cada mes conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "EMIM, EMS, registros del comercio exterior, índices de precios.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa IMCP 2018", "url": "https://www.inegi.org.mx/programas/imcp/2018/"},
        ],
    },
    "fbcf": {
        "titulo": "Indicador Mensual de la Formación Bruta de Capital Fijo (IMFBCF)",
        "antecedentes": "Mide la evolución mensual de la inversión en activos fijos (construcción y maquinaria). Disponible desde enero de 1993. Índices de volumen físico base 2018. Representatividad del 97.5% del valor alcanzado en 2018.",
        "periodicidad": "Mensual. Se publica los primeros días de cada mes conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "ENEC (23 tipos de obra), EMIM, registros del comercio exterior; valores deflactados con índices del Bureau of Labor Statistics de EE.UU. ponderados por tipo de cambio.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa IMFBCF 2018", "url": "https://www.inegi.org.mx/programas/imfbcf/2018/"},
        ],
    },
    "balanza_comercial": {
        "titulo": "Balanza Comercial de Mercancías de México (BCMM)",
        "antecedentes": "Registra el valor de las exportaciones e importaciones de mercancías. Disponible desde enero de 1993. Expresada en dólares americanos corrientes.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión de Información del INEGI.",
        "cobertura": "Nacional, con desagregación por tipo de bien y socio comercial.",
        "fuentes": "SAT, Secretaría de Economía, Banco de México e INEGI.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa BCMM", "url": "https://www.inegi.org.mx/programas/cm/2013/"},
        ],
    },
    "ind_ciclicos": {
        "titulo": "Sistema de Indicadores Cíclicos (SIC)",
        "antecedentes": "Monitorea el desempeño económico del país mediante los componentes Coincidente y Adelantado. Identifica puntos de giro y fases del ciclo económico. Base 2018=100.",
        "periodicidad": "Mensual. El Coincidente se actualiza dos meses después del periodo de referencia; el Adelantado, un mes después.",
        "cobertura": "Nacional.",
        "fuentes": "Agregado de indicadores económicos seleccionados por su correlación con el ciclo económico.",
        "ajuste": "Los componentes se obtienen mediante filtros estadísticos (Hodrick-Prescott y otros) sobre series ajustadas estacionalmente.",
        "links": [
            {"label": "Programa SIC", "url": "https://www.inegi.org.mx/programas/sic/"},
        ],
    },
    # ── Encuestas sectoriales ─────────────────────────────────────────────────
    "emim": {
        "titulo": "Encuesta Mensual de la Industria Manufacturera (EMIM)",
        "antecedentes": "Genera información sobre el comportamiento de las empresas manufactureras. Actualizada con base 2018 en 2023. Clasificación SCIAN 2018, sectores 31-33.",
        "periodicidad": "Mensual. Se publica en promedio 44 días naturales después de concluido el mes de referencia.",
        "cobertura": "Nacional. Marco probabilístico con cobertura mayor o igual a 80% del total de ingresos por dominio de estudio.",
        "fuentes": "Establecimientos manufactureros. Variables: días trabajados, personal ocupado, horas trabajadas, remuneraciones, capacidad de planta utilizada, volumen y valor de producción, ventas.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa EMIM 2018", "url": "https://www.inegi.org.mx/programas/emim/2018/"},
        ],
    },
    "enec": {
        "titulo": "Encuesta Nacional de Empresas Constructoras (ENEC)",
        "antecedentes": "Genera información sobre el comportamiento de las empresas constructoras. Permite estimar el valor de producción, personal ocupado y remuneraciones del sector. Base 2018.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "Establecimientos del sector construcción. Clasificación SCIAN 2018.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa ENEC 2018", "url": "https://www.inegi.org.mx/programas/enec/2018/"},
        ],
    },
    "comercio_mayoreo": {
        "titulo": "Encuesta Mensual sobre Empresas Comerciales (EMEC) — Comercio al por mayor",
        "antecedentes": "Genera información sobre ingresos, personal y remuneraciones del comercio al por mayor. Actualizada con base 2018 en 2023 con diseño estadístico probabilístico. Clasificación SCIAN 2018.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "Establecimientos comerciales. Variables: días trabajados, personal dependiente e independiente, remuneraciones, ingresos.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa EMEC 2018", "url": "https://www.inegi.org.mx/programas/emec/2018/"},
        ],
    },
    "comercio_menudeo": {
        "titulo": "Encuesta Mensual sobre Empresas Comerciales (EMEC) — Comercio al por menor",
        "antecedentes": "Genera información sobre ingresos, personal y remuneraciones del comercio al por menor. Actualizada con base 2018 en 2023 con diseño estadístico probabilístico. Clasificación SCIAN 2018.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "Establecimientos comerciales. Variables: días trabajados, personal dependiente e independiente, remuneraciones, ingresos.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa EMEC 2018", "url": "https://www.inegi.org.mx/programas/emec/2018/"},
        ],
    },
    "servicios": {
        "titulo": "Encuesta Mensual de Servicios (EMS)",
        "antecedentes": "Genera información sobre la actividad de los servicios privados no financieros. Índice ponderado tipo Laspeyres de base y referencia 2018. Disponible desde 2008.",
        "periodicidad": "Mensual. Se publica en promedio 51 días posteriores al mes de referencia.",
        "cobertura": "Nacional y por entidad federativa.",
        "fuentes": "Establecimientos de servicios privados no financieros. Clasificación SCIAN 2018.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa EMS 2018", "url": "https://www.inegi.org.mx/programas/ems/2018/"},
        ],
    },
    # ── Automotriz ────────────────────────────────────────────────────────────
    "autos_ligeros": {
        "titulo": "Registro Administrativo de la Industria Automotriz de Vehículos Ligeros (RAIAVL)",
        "antecedentes": "Registro de ventas, producción y exportaciones de vehículos ligeros en México. Cubre autos, camionetas, pickups y SUVs. Incluye vehículos híbridos y eléctricos con desglose específico.",
        "periodicidad": "Mensual. Se publica 2 veces al mes: cifras preliminares a principios del mes y definitivas a mediados.",
        "cobertura": "Nacional.",
        "fuentes": "Empresas fabricantes y distribuidoras afiliadas a la industria automotriz.",
        "ajuste": "Serie original. Se presentan variaciones anuales.",
        "links": [
            {"label": "Programa RAIAVL", "url": "https://www.inegi.org.mx/programas/raiavl/"},
        ],
    },
    "autos_pesados": {
        "titulo": "Registro Administrativo de la Industria Automotriz de Vehículos Pesados (RAIAVP)",
        "antecedentes": "Registro de ventas al menudeo y mayoreo, producción y exportaciones de vehículos pesados (camiones y autobuses). Cubre las 13 empresas que conforman el sector en México.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "Empresas fabricantes y distribuidoras de vehículos pesados.",
        "ajuste": "Serie original. Se presentan variaciones anuales.",
        "links": [
            {"label": "Programa RAIAVP", "url": "https://www.inegi.org.mx/programas/raiavp/"},
        ],
    },
    # ── Regional ──────────────────────────────────────────────────────────────
    "export_entidad": {
        "titulo": "Estadística de Exportaciones por Entidad Federativa (ETEF)",
        "antecedentes": "Estadística trimestral que ofrece información de las exportaciones de mercancías por entidad federativa de origen de la mercancía. Permite analizar la inserción de cada estado en el comercio exterior.",
        "periodicidad": "Trimestral. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "32 entidades federativas.",
        "fuentes": "SAT, Secretaría de Economía, Banco de México e INEGI.",
        "ajuste": "Serie original. Se presentan valores en millones de dólares.",
        "links": [
            {"label": "Programa ETEF", "url": "https://www.inegi.org.mx/programas/etef/"},
        ],
    },
    "pib_estatal": {
        "titulo": "Producto Interno Bruto por Entidad Federativa (PIBE)",
        "antecedentes": "Derivado del SCNM con año base 2018. Proporciona valores a precios corrientes y constantes, e índices de precios implícitos. Disponible desde 1980 (con serie retropolada).",
        "periodicidad": "Anual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "32 entidades federativas.",
        "fuentes": "Encuestas mensuales del INEGI (EMIM, ENEC, EMEC, EMS) y registros administrativos por entidad.",
        "ajuste": "No aplica ajuste estacional (serie anual).",
        "links": [
            {"label": "Programa PIB estatal 2018", "url": "https://www.inegi.org.mx/programas/pibent/2018/"},
        ],
    },
    "itaee_estatal": {
        "titulo": "Indicador Trimestral de la Actividad Económica Estatal (ITAEE)",
        "antecedentes": "Panorama sobre la evolución económica de las 32 entidades federativas. Difusión periódica desde 2009. Base 2018. Serie retropolada disponible desde 1980. Índices de volumen físico base fija 2018.",
        "periodicidad": "Trimestral. Se publica en promedio 120 días después del trimestre de referencia.",
        "cobertura": "32 entidades federativas.",
        "fuentes": "EMIM, ENEC, EMEC, EMS, ENOE y registros administrativos. Alineados a valores nacionales trimestrales con técnica proporcional Denton bivariada.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa ITAEE 2018", "url": "https://www.inegi.org.mx/programas/itaee/2018/"},
        ],
    },
    "imai_estatal": {
        "titulo": "Indicador Mensual de la Actividad Industrial por Entidad Federativa (IMAIEF)",
        "antecedentes": "Mide la evolución mensual de la actividad industrial por entidad federativa. Disponible desde enero de 2003. Índices de volumen físico base 2018. Clasifica actividades con SCIAN 2018. Ajustados a valores nacionales con técnica Denton.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión de Información del INEGI.",
        "cobertura": "32 entidades federativas.",
        "fuentes": "EMIM, ENEC, ENOE, registros administrativos de Pemex, CNH y CFE.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa IMAIEF", "url": "https://www.inegi.org.mx/programas/imaief/"},
        ],
    },
    "empleo_imss": {
        "titulo": "Trabajadores asegurados en el IMSS — Puestos de trabajo afiliados",
        "antecedentes": "El IMSS publica mensualmente el padrón de asegurados permanentes y eventuales. La métrica principal es 'ta' (puestos de trabajo afiliados), que excluye modalidades sin empleo asociado. Cobertura desde enero 2019 en microdatos abiertos.",
        "periodicidad": "Mensual. Se publica aproximadamente 10 días hábiles después del cierre de cada mes en datos.imss.gob.mx.",
        "cobertura": "Nacional, 32 entidades federativas, 9 divisiones económicas (clasificación IMSS Art. 196 LSS).",
        "fuentes": "IMSS — Datos Abiertos: datos.imss.gob.mx. Microdatos de asegurados, snapshot del último día del mes.",
        "ajuste": "Sin ajuste estacional. Datos originales (snapshot mensual).",
        "links": [
            {"label": "Datos abiertos IMSS", "url": "https://datos.imss.gob.mx"},
        ],
    },
    # ── Sentimiento ───────────────────────────────────────────────────────────
    "confianza_consumidor": {
        "titulo": "Indicador de Confianza del Consumidor (ICC) — ENCO",
        "antecedentes": "Mide la percepción de los consumidores sobre su situación económica actual y futura, y la del país. Continua desde abril de 2001. Levantamiento en las 32 ciudades más importantes del país.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "32 ciudades principales del país.",
        "fuentes": "INEGI y Banco de México. Encuesta Nacional sobre Confianza del Consumidor (ENCO). Levantamiento durante los primeros días del mes.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS.",
        "links": [
            {"label": "Programa ENCO", "url": "https://www.inegi.org.mx/programas/enco/"},
        ],
    },
    "emoe_ipm": {
        "titulo": "Indicador de Pedidos Manufactureros (IPM) — EMOE",
        "antecedentes": "Mide el nivel de pedidos del sector manufacturero con base en opinión empresarial. Información de Interés Nacional desde diciembre de 2021. Base 2018. Actualizado en 2018 y 2023 con cambio de año base de las EEN.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "INEGI y Banco de México. EMOE: encuesta de opinión a directivos de empresas manufactureras.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS para componentes con patrón estacional definido.",
        "links": [
            {"label": "Programa EMOE 2018", "url": "https://www.inegi.org.mx/programas/emoe/2018/"},
        ],
    },
    "emoe_iat": {
        "titulo": "Indicador Agregado de Tendencia (IAT) — EMOE",
        "antecedentes": "Mide las expectativas empresariales sobre la actividad económica. Información de Interés Nacional desde diciembre de 2021. El IAT y el IGOET sintetizan la opinión de directivos. Base 2018.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "INEGI. EMOE: encuesta de opinión empresarial sobre tendencia, construcción, manufacturas, comercio y servicios.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS cuando existe patrón estacional definido.",
        "links": [
            {"label": "Programa EMOE 2018", "url": "https://www.inegi.org.mx/programas/emoe/2018/"},
        ],
    },
    "emoe_ice": {
        "titulo": "Indicador de Confianza Empresarial (ICE) — EMOE",
        "antecedentes": "Mide la confianza de los directivos sobre la situación económica actual y futura de sus empresas y del país. Información de Interés Nacional desde diciembre de 2021. El IGOEC resume la opinión global. Base 2018.",
        "periodicidad": "Mensual. Se publica conforme al Calendario de Difusión del INEGI.",
        "cobertura": "Nacional.",
        "fuentes": "INEGI. EMOE: encuesta a directivos de empresas de manufacturas, construcción, comercio y servicios. ICE de Comercio no presenta patrón estacional definido.",
        "ajuste": "Series originales ajustadas estacionalmente con X-13ARIMA-SEATS. Solo algunos componentes de manufacturas y construcción muestran patrón estacional.",
        "links": [
            {"label": "Programa EMOE 2018", "url": "https://www.inegi.org.mx/programas/emoe/2018/"},
        ],
    },
}

CATEGORIA_LABEL = {
    "macro": "Macro",
    "actividad": "Actividad",
    "encuestas_sectoriales": "Encuestas",
    "precios": "Precios",
    "empleo": "Empleo",
    "automotriz": "Automotriz",
    "regional": "Regional",
    "sentimiento": "Sentimiento",
}

# Campo principal, secundario, unidad y label para resumen
CAMPO_PRINCIPAL = {
    "pib_anual":            {"principal": "PIB_anual", "sec": None, "unidad": "%", "label": "PIB anual (resumen)", "chart_tipo": "bar_vertical", "n_display": 21, "chart_titulo": "Crecimiento del PIB anual"},
    "inflacion_resumen":    {"principal": "INPC_anual", "sec": None, "unidad": "%", "label": "Inflación anual (resumen)", "chart_tipo": "bar_grouped", "grouped_cols": ["INPC_anual", "Subyacente_anual", "No_subyacente_anual"], "n_display": 12, "chart_titulo": "Inflación por componente · variación anual"},
    "igae_ioae_resumen":    {"tabular": True, "unidad": "%", "label": "IGAE / IOAE por sector"},
    "pib_trimestral":       {"principal": "Anual", "sec": "Trimestral", "unidad": "%", "label": "PIB anual"},
    "pib_por_actividad":    {"principal": "Terciarias_Anual", "sec": "Secundarias_Anual", "unidad": "%", "label": "PIB por actividad", "chart_tipo": "bar_grouped", "grouped_cols": ["Primarias_Anual", "Mineria_Anual", "Construccion_Anual", "Manufacturas_Anual", "Terciarias_Anual"], "n_display": 12, "chart_titulo": "PIB por actividad · variación % anual"},
    "igae":                 {"principal": "Total_Anual", "sec": "Total_Mensual", "unidad": "%", "label": "IGAE anual"},
    "actividad_industrial": {"principal": "Total", "sec": "Manufactureras", "unidad": "%", "label": "IMAI total"},
    "consumo_privado":      {"principal": "Total_Anual", "sec": "Total_Mensual", "unidad": "%", "label": "Consumo privado"},
    "fbcf":                 {"principal": "Total_Anual", "sec": "Total_Mensual", "unidad": "%", "label": "FBCF anual"},
    "balanza_comercial":    {"principal": "Exportaciones_totales_Anual", "sec": "Importaciones_totales_Anual", "unidad": "%", "label": "Exportaciones"},
    "ind_ciclicos":         {"principal": "Adelantado", "sec": "Coincidente", "unidad": "pts", "label": "Cíclico adelantado"},
    "emim":                 {"principal": "Volumen_producción", "sec": "Personal_ocupado", "unidad": "%", "label": "EMIM producción"},
    "enec":                 {"principal": "Valor_producción", "sec": "Personal_ocupado", "unidad": "%", "label": "ENEC valor"},
    "comercio_mayoreo":     {"principal": "Ingresos_totales", "sec": "Personal_ocupado", "unidad": "%", "label": "Mayoreo ingresos"},
    "comercio_menudeo":     {"principal": "Personal_ocupado", "sec": "Mercancías_compradas", "unidad": "%", "label": "Menudeo personal"},
    "servicios":            {"principal": "Ingresos_totales", "sec": "Personal_ocupado", "unidad": "%", "label": "Servicios ingresos"},
    "inpc_mensual":         {"principal": "INPC_Anual", "sec": "Subyacente_Anual", "unidad": "%", "label": "INPC anual"},
    "inpc_quincenal":       {"principal": "INPC_Anual", "sec": "Subyacente_Anual", "unidad": "%", "label": "INPC 1Q mar"},
    "inpp":                 {"principal": "Sin_petróleo_c_serv_Anual", "sec": "Con_petróleo_c_serv_Anual", "unidad": "%", "label": "INPP sin petróleo"},
    "enoe_trimestral":      {"tabular": True, "unidad": "%", "label": "Indicadores ENOE"},
    "autos_ligeros":        {"principal": "Ventas", "sec": None, "unidad": "%", "label": "Autos ligeros", "chart_tipo": "bar_grouped", "grouped_cols": ["Ventas", "Producción", "Exportación"], "n_display": 24, "chart_titulo": "Autos ligeros · var. % anual"},
    "autos_pesados":        {"principal": "Ventas_Menudeo", "sec": None, "unidad": "%", "label": "Autos pesados", "chart_tipo": "bar_grouped", "grouped_cols": ["Ventas_Menudeo", "Ventas_Mayoreo", "Exportación", "Producción"], "n_display": 24, "chart_titulo": "Autos pesados · var. % anual"},
    "export_entidad":       {"tabular": True, "unidad": "%", "label": "Exportaciones por entidad"},
    "empleo_imss":          {"tabular": True, "unidad": " M", "label": "Empleo formal IMSS"},
    "confianza_consumidor": {"principal": "Mensual", "sec": "Anual", "unidad": "pts", "label": "Conf. consumidor"},
    "emoe_ipm":             {"principal": "Mensual", "sec": "Anual", "unidad": "pts", "label": "EMOE IPM"},
    "emoe_iat":             {"principal": "Mensual", "sec": "Anual", "unidad": "pts", "label": "EMOE IAT"},
    "emoe_ice":             {"principal": "Mensual", "sec": "Anual", "unidad": "pts", "label": "EMOE ICE"},
    "enoe_mensual":         {"principal": "Tasa_desocupacion_Total", "sec": "Tasa_informalidad", "unidad": "%", "label": "Desocupación (ENOE mensual)"},
    "pib_estatal":          {"tabular": True, "unidad": "%", "label": "PIB estatal variación anual"},
    "itaee_estatal":        {"tabular": True, "unidad": "%", "label": "ITAEE por entidad"},
    "imai_estatal":         {"tabular": True, "unidad": "%", "label": "IMAI estatal"},
}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Friendly labels para series (chart legend + table headers). Se aplica sobre los raw keys.
SERIE_LABEL_MAP = {
    "PIB_anual": "Var. anual",
    "INPC_anual": "INPC anual",
    "INPC_Anual": "INPC anual",
    "Subyacente_Anual": "Subyacente anual",
    "Anual": "Var. anual",
    "Trimestral": "Var. trimestral",
    "Mensual": "Var. mensual",
    "Terciarias_Anual": "Terciarias",
    "Secundarias_Anual": "Secundarias",
    "Primarias_Anual": "Primarias",
    "Mineria_Anual": "Minería",
    "Energia_agua_gas_Anual": "Energía/agua/gas",
    "Construccion_Anual": "Construcción",
    "Manufacturas_Anual": "Manufacturas",
    "Comercio_mayor_Anual": "Comercio mayoreo",
    "Comercio_menor_Anual": "Comercio menudeo",
    "Transportes_Anual": "Transportes",
    "Financieros_Anual": "Financieros",
    "Gubernamentales_Anual": "Gubernamentales",
    "Total_Anual": "Total anual",
    "Total_Mensual": "Total mensual",
    "IGAE_Nowcast": "IGAE nowcast",
    "IGAE_Inferior": "IC inferior 95%",
    "IGAE_Superior": "IC superior 95%",
    "Total": "Total",
    "Manufactureras": "Manufactureras",
    "Volumen_producción": "Volumen producción",
    "Personal_ocupado": "Personal ocupado",
    "Valor_producción": "Valor producción",
    "Ingresos_totales": "Ingresos totales",
    "Exportaciones_totales_Anual": "Exportaciones (var. anual)",
    "Importaciones_totales_Anual": "Importaciones (var. anual)",
    "Sin_petróleo_c_serv_Anual": "Sin petróleo c/servicios",
    "Con_petróleo_c_serv_Anual": "Con petróleo c/servicios",
    "Adelantado": "Adelantado",
    "Coincidente": "Coincidente",
    "Ventas": "Ventas",
    "Producción": "Producción",
    "Ventas_Menudeo": "Ventas menudeo",
    "Tasa_desocupacion_Total": "Desocupación (%)",
    "Tasa_desocupacion_Hombres": "Desocupación hombres (%)",
    "Tasa_desocupacion_Mujeres": "Desocupación mujeres (%)",
    "Tasa_participacion_Total": "Participación (%)",
    "Tasa_participacion_Hombres": "Participación hombres (%)",
    "Tasa_participacion_Mujeres": "Participación mujeres (%)",
    "Tasa_subocupacion": "Subocupación (%)",
    "Tasa_informalidad": "Informalidad (%)",
}


def serie_label(key: str) -> str:
    if key in SERIE_LABEL_MAP:
        return SERIE_LABEL_MAP[key]
    return key.replace("_", " ")


# Labels para headers de columnas en indicadores tabulares
COL_LABEL_MAP = {
    "Var_anual": "Var. anual (%)",
    "Var_trimestral": "Var. trimestral (%)",
    "Var_mensual": "Var. mensual (%)",
    "2025_MDP": "2025 (MDP)",
    "MDD": "MDD",
    "T4_2024": "T4-24",
    "T4_2025": "T4-25",
    "Dif_2025-2024_pp": "Δ pp",
    "Participación": "Participación (%)",
    "Concepto": "Concepto",
    "Entidad": "Entidad",
    "Lugar": "Lugar",
}


def friendly_col(key: str) -> str:
    """Devuelve etiqueta legible para header de tabla tabular.
    Maneja patrón PREFIX_mmm-YY (ej. IGAE_ene-26) reemplazando underscore por espacio.
    """
    if key in COL_LABEL_MAP:
        return COL_LABEL_MAP[key]
    # Patrones dinámicos ENOE pivot. Orden importa: chequear Dif_*_Abs antes de *_Abs.
    if key.startswith("Dif_") and key.endswith("_pp"):
        return "Δ pp"
    if key.startswith("Dif_") and key.endswith("_Abs"):
        return "Δ abs."
    if key.endswith("_Abs"):
        return key.replace("_Abs", " abs.")
    return key.replace("_", " ")


def num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    try:
        return round(float(v), 2)
    except (ValueError, TypeError):
        return None


def estadisticos_descriptivos(serie: list[float | None], ventana: int = 120) -> dict:
    """Calcula estadísticos sobre últimos N valores válidos de la serie.

    ventana=120 = 10 años para series mensuales.
    Devuelve dict con count, mean, std, median, min, max, p25, p50, p75, p95.
    """
    validos = [v for v in (serie or []) if v is not None]
    if len(validos) < 2:
        return {}
    sample = validos[-ventana:] if len(validos) > ventana else validos
    n = len(sample)
    sample_sorted = sorted(sample)
    mean = sum(sample) / n
    var = sum((x - mean) ** 2 for x in sample) / n
    std = var ** 0.5

    def percentile(p: float) -> float:
        idx = int(p / 100 * (n - 1))
        return sample_sorted[idx]

    return {
        "count": n,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "min": round(sample_sorted[0], 2),
        "max": round(sample_sorted[-1], 2),
        "p25": round(percentile(25), 2),
        "p50": round(percentile(50), 2),
        "p75": round(percentile(75), 2),
        "p95": round(percentile(95), 2),
    }


def comparativos_lag(serie: list[float | None], periodos: list[str]) -> dict:
    """Devuelve deltas vs lag 1, 3, 6, 12, 24 meses."""
    if not serie:
        return {}
    ult = serie[-1] if serie else None
    if ult is None:
        return {}
    out = {}
    lags = [(1, "1m"), (3, "3m"), (6, "6m"), (12, "12m"), (24, "24m")]
    for k, label in lags:
        if len(serie) > k:
            anterior = serie[-1 - k]
            if anterior is not None:
                out[label] = {
                    "delta": round(ult - anterior, 2),
                    "valor": round(anterior, 2),
                    "periodo": periodos[-1 - k] if len(periodos) > k else None,
                }
    return out


def mejor_peor_historico(serie: list[float | None], periodos: list[str]) -> dict:
    """Identifica récord positivo y negativo en la serie completa."""
    pares = [(v, p) for v, p in zip(serie or [], periodos or []) if v is not None]
    if not pares:
        return {}
    mejor = max(pares, key=lambda x: x[0])
    peor = min(pares, key=lambda x: x[0])
    return {
        "mejor": {"valor": round(mejor[0], 2), "periodo": mejor[1]},
        "peor": {"valor": round(peor[0], 2), "periodo": peor[1]},
    }


def z_score(serie: list[float | None], ventana: int = 120) -> dict:
    """Z-score del último valor sobre media y σ de últimos N."""
    validos = [v for v in (serie or []) if v is not None]
    if len(validos) < 24:
        return {}
    sample = validos[-ventana:] if len(validos) > ventana else validos
    n = len(sample)
    mean = sum(sample) / n
    var = sum((x - mean) ** 2 for x in sample) / n
    std = var ** 0.5
    if std == 0:
        return {}
    z = (validos[-1] - mean) / std
    if abs(z) >= 2:
        cat = "extremo"
    elif abs(z) >= 1:
        cat = "atipico"
    else:
        cat = "normal"
    return {"z": round(z, 2), "categoria": cat}


def percentil_ultimo(serie: list[float | None], ventana: int = 120) -> dict:
    """Percentil del último valor en distribución histórica."""
    validos = [v for v in (serie or []) if v is not None]
    if len(validos) < 24:
        return {}
    sample = validos[-ventana:] if len(validos) > ventana else validos
    ult = validos[-1]
    debajo = sum(1 for v in sample if v <= ult)
    p = round(debajo / len(sample) * 100)
    return {"p": p, "muestra": len(sample)}


# Configuración de componentes para EMOE e ICC
# Cada entrada: (nombre_display, col_nivel, col_mensual, col_anual)
EMOE_ICC_COMPONENTES: dict[str, list] = {
    "emoe_ipm": [
        ("IPM",                 "IPM_Nivel",                 "Mensual",                    "Anual"),
        ("Pedidos esperados",   "Pedidos_esperados_Nivel",   "Pedidos_esperados_Mensual",   "Pedidos_esperados_Anual"),
        ("Producción esperada", "Produccion_esperada_Nivel", "Produccion_esperada_Mensual", "Produccion_esperada_Anual"),
        ("Personal ocupado",    "Personal_ocupado_Nivel",    "Personal_ocupado_Mensual",    "Personal_ocupado_Anual"),
        ("Entrega de insumos",  "Entrega_insumos_Nivel",     "Entrega_insumos_Mensual",     "Entrega_insumos_Anual"),
        ("Inventarios",         "Inventarios_Nivel",         "Inventarios_Mensual",         "Inventarios_Anual"),
    ],
    "emoe_iat": [
        ("IAT",          "IAT_Nivel",               "Mensual",                  "Anual"),
        ("Construcción", "IAT_construccion_Nivel",  "IAT_construccion_Mensual", "IAT_construccion_Anual"),
        ("Comercio",     "IAT_comercio_Nivel",      "IAT_comercio_Mensual",     "IAT_comercio_Anual"),
    ],
    "emoe_ice": [
        ("ICE",          "ICE_Nivel",               "Mensual",                  "Anual"),
        ("Manufacturas", "ICE_manufacturas_Nivel",  "ICE_manufacturas_Mensual", "ICE_manufacturas_Anual"),
        ("Construcción", "ICE_construccion_Nivel",  "ICE_construccion_Mensual", "ICE_construccion_Anual"),
        ("Comercio",     "ICE_comercio_Nivel",      "ICE_comercio_Mensual",     "ICE_comercio_Anual"),
        ("Servicios",    "ICE_servicios_Nivel",     "ICE_servicios_Mensual",    "ICE_servicios_Anual"),
    ],
    "confianza_consumidor": [
        ("ICC",                      "ICC_Nivel",             "Mensual",                "Anual"),
        ("Hogar: situación actual",  "Hogar_actual_Nivel",    "Hogar_actual_Mensual",   "Hogar_actual_Anual"),
        ("Hogar: situación futura",  "Hogar_futura_Nivel",    "Hogar_futura_Mensual",   "Hogar_futura_Anual"),
        ("País: situación actual",   "Pais_actual_Nivel",     "Pais_actual_Mensual",    "Pais_actual_Anual"),
        ("País: situación futura",   "Pais_futura_Nivel",     "Pais_futura_Mensual",    "Pais_futura_Anual"),
        ("Compra de duraderos",      "Compra_durables_Nivel", "Compra_durables_Mensual","Compra_durables_Anual"),
    ],
}
UMBRAL_PMI = 50  # nivel de expansión/contracción para EMOE e ICC


def compute_ma12(arr: list[float | None]) -> list[float | None]:
    """Media móvil de 12 periodos. Exige ventana completa de 12 valores válidos
    (igual que composites.py): los primeros ~11 puntos y los tramos con huecos
    quedan None en vez de ser un promedio parcial mal etiquetado como MA12."""
    out = []
    for i in range(len(arr)):
        window = [x for x in arr[max(0, i - 11):i + 1] if isinstance(x, (int, float))]
        out.append(round(sum(window) / 12, 2) if len(window) == 12 else None)
    return out


def asignar_alerta(id_: str, valor: float | None, thresholds: dict) -> str:
    """Evalua thresholds.json. Default: 'neutro'."""
    t_id = thresholds.get(id_)
    if not t_id or valor is None:
        return "neutro"
    campo_key = next(iter(t_id))
    t = t_id[campo_key]
    tipo = t["tipo"]
    v = valor
    if tipo == "max":
        if v < t["verde_max"]:
            return "verde"
        if v < t["amarillo_max"]:
            return "amarillo"
        return "rojo"
    if tipo == "min":
        if v >= t["verde_min"]:
            return "verde"
        if v >= t["amarillo_min"]:
            return "amarillo"
        return "rojo"
    return "neutro"


def proxima_publicacion(id_: str, calendar: dict) -> dict:
    c = calendar.get(id_, {})
    prox = c.get("proximas_publicaciones", [])
    if not prox:
        return {"fecha": "—", "tipo": "Sin fecha en calendario"}
    p = prox[0]
    y, m, d = p["fecha"].split("-")
    fecha_friendly = f"{int(d)} {MESES[int(m) - 1]} {y}"
    sumtxt = p.get("evento_ics", "")
    sumtxt = re.sub(r"\s*Año base[^.]*\.", "", sumtxt)
    sumtxt = re.sub(r"\s*Cifras[^.]*\.", "", sumtxt)
    sumtxt = re.sub(r"\s*Base 2ª[^.]*\.", "", sumtxt)
    sumtxt = sumtxt.split(".")[0].strip()
    return {"fecha": fecha_friendly, "fecha_iso": p["fecha"], "tipo": sumtxt[:80]}


def build_indicator(meta: dict, data_dir: Path, calendar: dict, thresholds: dict) -> dict | None:
    id_ = meta["id"]
    cfg = CAMPO_PRINCIPAL.get(id_, {})
    if cfg.get("tabular"):
        return build_tabular(meta, cfg, data_dir, calendar, thresholds)

    f = data_dir / f"{id_}.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    periodos = data.get("periodos", [])
    principal = cfg["principal"]
    sec = cfg.get("sec")
    sec2 = cfg.get("sec2")

    serie_principal = [num(r.get(principal)) for r in data.get("series", [])]
    ma12 = compute_ma12(serie_principal)

    # Serie larga (60 meses) para chart con stats
    L = min(60, len(periodos))
    periodos_long = periodos[-L:]
    serie_long = serie_principal[-L:]
    ma12_long = ma12[-L:]

    # Series secundarias completas (hasta 60m)
    raw_series = data.get("series", [])
    series_long = {serie_label(principal): serie_long}
    if sec:
        series_long[serie_label(sec)] = [num(r.get(sec)) for r in raw_series[-L:]]
    if sec2:
        series_long[serie_label(sec2)] = [num(r.get(sec2)) for r in raw_series[-L:]]

    # Mantener compat: short de 13 para home cards y resto
    N = min(cfg.get("n_display", 13), len(periodos))
    periodos_short = periodos_long[-N:]
    serie_short = serie_long[-N:]
    ma12_short = ma12_long[-N:]
    series_obj = {k: v[-N:] for k, v in series_long.items()}

    # Construir grouped_series para chart_tipo == "bar_grouped"
    grouped_series = None
    if cfg.get("chart_tipo") == "bar_grouped" and cfg.get("grouped_cols"):
        raw_all = data.get("series", [])[-N:]
        grouped_series = {}
        for col in cfg["grouped_cols"]:
            grouped_series[serie_label(col)] = [num(r.get(col)) for r in raw_all]

    ultimo = serie_short[-1] if serie_short else None
    previo = serie_short[-2] if len(serie_short) >= 2 else None
    delta = round(ultimo - previo, 2) if (ultimo is not None and previo is not None) else None
    ma12_ult = ma12_short[-1] if ma12_short else None
    alerta = asignar_alerta(id_, ultimo, thresholds)

    # Stats sobre serie completa
    stats = estadisticos_descriptivos(serie_principal)
    lags = comparativos_lag(serie_principal, periodos)
    extremos = mejor_peor_historico(serie_principal, periodos)
    z = z_score(serie_principal)
    percentil = percentil_ultimo(serie_principal)

    prox = proxima_publicacion(id_, calendar)
    manual_prox = data.get("proxima_actualizacion_manual")
    if manual_prox:
        prox = _parse_manual_prox(manual_prox, prox)

    # Desglose sectorial IGAE: snapshot del último período con var. anual por sector
    _desglose_sectorial = None
    # Recuadros cabecera INPC quincenal — construido desde BIE, no requiere inyección manual
    _recuadros_inpc_auto = None
    if id_ == "inpc_quincenal" and periodos:
        _series_inpc = data.get("series") or []
        last_row = _series_inpc[-1] if _series_inpc else {}
        nosub_q = last_row.get("No_subyacente_Quincenal") or last_row.get("No subyacente_Quincenal")
        nosub_a = last_row.get("No_subyacente_Anual") or last_row.get("No subyacente_Anual")
        _recuadros_inpc_auto = {
            "periodo": periodos[-1],
            "etiqueta_variacion": "quincenal",
            "componentes": [
                {"nombre": "Inflación general", "var_mensual": last_row.get("INPC_Quincenal"),      "var_anual": last_row.get("INPC_Anual")},
                {"nombre": "Subyacente",         "var_mensual": last_row.get("Subyacente_Quincenal"), "var_anual": last_row.get("Subyacente_Anual")},
                {"nombre": "No subyacente",      "var_mensual": nosub_q,                             "var_anual": nosub_a},
            ],
        }

    if id_ == "igae":
        series_data = data.get("series") or [{}]
        last_row = series_data[-1] if series_data else {}
        sector_map = {
            "Total": last_row.get("Total_Anual"),
            "Actividades primarias": last_row.get("Primarias_Anual"),
            "Actividades secundarias": last_row.get("Secundarias_Anual"),
            "  Minería": last_row.get("Mineria_Anual"),
            "  Energía / agua / gas": last_row.get("Energia_agua_gas_Anual"),
            "  Construcción": last_row.get("Construccion_Anual"),
            "  Manufacturas": last_row.get("Manufacturas_Anual"),
            "Actividades terciarias": last_row.get("Terciarias_Anual"),
            "  Comercio al mayoreo": last_row.get("Comercio_mayoreo_Anual"),
            "  Comercio al menudeo": last_row.get("Comercio_menudeo_Anual"),
            "  Transportes": last_row.get("Transportes_Anual"),
            "  Serv. financieros": last_row.get("Servicios_financieros_Anual"),
            "  Serv. inmobiliarios": last_row.get("Servicios_inmobiliarios_Anual"),
            "  Serv. profesionales": last_row.get("Servicios_profesionales_Anual"),
            "  Act. gubernamentales": last_row.get("Actividades_gubernamentales_Anual"),
        }
        _desglose_sectorial = {
            "periodo": periodos[-1] if periodos else "—",
            "filas": [{"sector": k, "var_anual": round(v, 2)} for k, v in sector_map.items() if v is not None],
        }

    # EMOE e ICC: tabla de componentes (nivel, Δ mensual, Δ anual) + meses consecutivos sobre/bajo 50
    _componentes_emoe = None
    _meses_consec = None
    if id_ in EMOE_ICC_COMPONENTES:
        _series_emoe = data.get("series") or []
        last_row = _series_emoe[-1] if _series_emoe else {}
        comp_cfg = EMOE_ICC_COMPONENTES[id_]
        filas_comp = []
        for nombre_comp, col_niv, col_men, col_anu in comp_cfg:
            niv = num(last_row.get(col_niv))
            men = num(last_row.get(col_men))
            anu = num(last_row.get(col_anu))
            if niv is not None:
                filas_comp.append({
                    "componente": nombre_comp,
                    "nivel": round(niv, 2),
                    "mensual": round(men, 2) if men is not None else None,
                    "anual": round(anu, 2) if anu is not None else None,
                    "sobre_umbral": niv >= UMBRAL_PMI,
                })
        _componentes_emoe = {
            "periodo": periodos[-1] if periodos else "—",
            "umbral": UMBRAL_PMI,
            "filas": filas_comp,
        }
        # Meses consecutivos del índice global sobre/bajo umbral
        col_niv_global = comp_cfg[0][1]
        niveles_global = [num(r.get(col_niv_global)) for r in data.get("series", [])]
        niveles_global = [v for v in niveles_global if v is not None]
        if niveles_global:
            ultimo_niv = niveles_global[-1]
            es_sobre = ultimo_niv >= UMBRAL_PMI
            consec = 0
            for v in reversed(niveles_global):
                if (v >= UMBRAL_PMI) == es_sobre:
                    consec += 1
                else:
                    break
            _meses_consec = {
                "n": consec,
                "toda_serie": consec >= len(niveles_global),
                "direccion": "sobre" if es_sobre else "bajo",
                "umbral": UMBRAL_PMI,
                "nivel_actual": round(ultimo_niv, 2),
            }

    return {
        "id": id_,
        "nombre": meta["nombre"],
        "categoria": CATEGORIA_LABEL.get(meta["categoria"], meta["categoria"]),
        "unidad": cfg.get("unidad", meta.get("unidad", "")),
        "fuente": data.get("fuente_url", meta.get("boletin_url", "")),
        "proximaPub": prox,
        "campoDefault": principal,
        "campoDefaultLabel": serie_label(principal),
        "periodos": periodos_short,
        "series": series_obj,
        "ma12": ma12_short,
        "ultimo": ultimo,
        "previo": previo,
        "delta": delta,
        "ma12_ult": ma12_ult,
        "alerta": alerta,
        "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
        "_chart_tipo": cfg.get("chart_tipo"),
        "_chart_titulo": cfg.get("chart_titulo"),
        "grouped_series": grouped_series,
        "_label_tabla": cfg.get("label", meta["nombre"]),
        "_productos": data.get("_productos"),
        "_entidades_ciudades": data.get("_entidades_ciudades"),
        # Stats y enriquecimiento (iteración 2A)
        "periodos_long": periodos_long,
        "series_long": series_long,
        "ma12_long": ma12_long,
        "stats": stats,
        "lags": lags,
        "extremos": extremos,
        "z_score": z,
        "percentil": percentil,
        # Enriquecimiento comunicados
        "_metodologia": METODOLOGIA_MAP.get(id_),
        "_desglose_sectorial": _desglose_sectorial,
        "_componentes_emoe": _componentes_emoe,
        "_meses_consec": _meses_consec,
        "_recuadros_inpc": _recuadros_inpc_auto or data.get("_recuadros_inpc"),
        "_cuadro1": data.get("_cuadro1"),
    }


def build_tabular(meta: dict, cfg: dict, data_dir: Path, calendar: dict, thresholds: dict) -> dict | None:
    id_ = meta["id"]
    f = data_dir / f"{id_}.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text(encoding="utf-8"))
    base = {
        "id": id_,
        "nombre": meta["nombre"],
        "categoria": CATEGORIA_LABEL.get(meta["categoria"], meta["categoria"]),
        "unidad": cfg.get("unidad", "%"),
        "fuente": data.get("fuente_url", meta.get("boletin_url", "")),
        "proximaPub": proxima_publicacion(id_, calendar),
        "tabular": True,
        "_label_tabla": cfg["label"],
    }
    # Override next-pub from data file cuando exista "proxima_actualizacion_manual"
    manual_prox = data.get("proxima_actualizacion_manual")
    if manual_prox:
        base["proximaPub"] = _parse_manual_prox(manual_prox, base.get("proximaPub", {}))

    if id_ == "enoe_trimestral":
        # Columnas dinámicas: el composite las renombra usando periodos reales (T4-24, T4-25, etc.)
        p_act = data.get("_periodo_actual") or "T_act"
        p_prev = data.get("_periodo_prev") or "T_prev"
        col_pct_act = p_act
        col_pct_prev = p_prev
        col_dif_pp = f"Dif_{p_act}-{p_prev}_pp"
        col_abs_act = f"{p_act}_Abs"
        col_abs_prev = f"{p_prev}_Abs"
        col_dif_abs = f"Dif_{p_act}-{p_prev}_Abs"
        # Buscar primera Desocupada (bajo bloque Total). Concepto viene con sangría: "    Desocupada".
        desoc = None
        for r in data["series"]:
            concepto = (r.get("Concepto") or "").strip().lower()
            if concepto.startswith("desocupa"):
                desoc = r
                break
        valor = num(desoc.get(col_pct_act)) if desoc else None
        valor_prev = num(desoc.get(col_pct_prev)) if desoc else None
        delta = round(valor - valor_prev, 2) if (valor is not None and valor_prev is not None) else None
        # Detectar columnas disponibles en datos
        sample = data["series"][0] if data.get("series") else {}
        available = data.get("columnas_normalizadas") or list(sample.keys())
        # Orden preferente: Concepto, prev_Abs, act_Abs, dif_Abs, prev_pct, act_pct, dif_pp
        preferidas = ["Concepto", col_abs_prev, col_abs_act, col_dif_abs, col_pct_prev, col_pct_act, col_dif_pp]
        cols = [c for c in preferidas if c in available]
        # PEA flow: extraer bloques Total para diagrama de flujo
        _pea_flow = None
        try:
            flow_conceptos = ["Total", "PEA", "Ocupada", "Desocupada", "PNEA", "Disponible", "No disponible"]
            flow_rows = []
            for r in data["series"]:
                concepto_raw = r.get("Concepto", "")
                concepto_strip = concepto_raw.strip()
                if concepto_strip in flow_conceptos:
                    flow_rows.append({
                        "concepto": concepto_strip,
                        "abs_act": r.get(col_abs_act),
                        "abs_prev": r.get(col_abs_prev),
                        "pct_act": r.get(col_pct_act),
                        "pct_prev": r.get(col_pct_prev),
                    })
            # Sólo tomar el bloque Total (primeras 7 filas que coincidan)
            flow_rows = flow_rows[:7]
            if flow_rows:
                _pea_flow = {"periodo": p_act, "filas": flow_rows}
        except Exception:
            _pea_flow = None

        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": data["series"][:21],
            "coloreable_cols": [c for c in (col_dif_pp,) if c in cols],
            "ultimo": valor, "delta": delta, "ma12_ult": None,
            "alerta": asignar_alerta(id_, valor, thresholds),
            "_label_tabla": "Tasa desocupación",
            "_periodo_tabular": p_act,
            "_previo_label_tabular": f"vs {p_prev}",
            "_chart_tipo": "bar_grouped_horizontal",
            "_col_abs_act": col_abs_act,
            "_col_abs_prev": col_abs_prev,
            "_p_act": p_act,
            "_p_prev": p_prev,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get("enoe_trimestral"),
            "_pea_flow": _pea_flow,
        }}
    if id_ == "igae_ioae_resumen":
        cols = data.get("columnas_normalizadas", [])
        # Todas las columnas numéricas en este resumen son variaciones %, así que todas coloreables
        coloreable = [c for c in cols if c != cols[0]] if cols else []
        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": data["series"],
            "coloreable_cols": coloreable,
            "ultimo": None, "delta": None, "ma12_ult": None, "alerta": "neutro",
            "_periodo_tabular": "—",
            "_metodologia": METODOLOGIA_MAP.get("igae_ioae_resumen"),
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
        }}
    if id_ == "export_entidad":
        from tile_map import build_tile_grid_svg
        # Excluir agregado nacional para que "top" sea entidad real
        entidades = [r for r in data["series"] if r.get("Entidad") != "Estados Unidos Mexicanos"]
        # Soporta dos nombres: legacy 'MDD' y nuevo 'MDD_anual' del ingest BIE
        def _mdd(r):
            return r.get("MDD") if r.get("MDD") is not None else r.get("MDD_anual") or 0
        # Ordenar todas las entidades por MDD desc y agregar ranking
        filas_todas = sorted(entidades, key=_mdd, reverse=True)
        total = sum(_mdd(r) for r in entidades) or 1
        for i, r in enumerate(filas_todas):
            r["Lugar"] = i + 1
            if r.get("Participación") is None:
                r["Participación"] = round(_mdd(r) / total * 100, 2)
        filas = filas_todas  # mostrar todas (32 entidades)
        top = filas[0] if filas else {}
        cols = ["Lugar", "Entidad"] + [c for c in ("MDD_trimestral", "MDD_anual", "MDD", "Var_anual", "Participación") if c in (top or {})]
        if "Participación" not in cols:
            cols.append("Participación")
        # Tile grid map de México
        valores_mapa = {r["Entidad"]: r.get("Participación") for r in entidades}
        tile_svg = build_tile_grid_svg(valores_mapa, unidad="%", palette="teal", label_positivo="mayor partic.", label_negativo="menor partic.")
        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": filas,
            "coloreable_cols": ["Var_anual"] if "Var_anual" in cols else [],
            "ultimo": top.get("Participación"),
            "delta": None, "ma12_ult": None, "alerta": "neutro",
            "_label_tabla": "Participación de entidad líder",
            "_periodo_tabular": data.get("periodo_referencia") or "T4-25",
            "_top_concepto": top.get("Entidad"),
            "_chart_tipo": "bar_horizontal",
            "_tile_map_svg": tile_svg,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get(id_),
        }}
    if id_ == "pib_estatal":
        from tile_map import build_tile_grid_svg
        # Soporta nuevo ingest BIE (Participacion, IVF_2018) y legacy (Var_anual)
        sample = (data["series"][0] if data.get("series") else {}) or {}
        if "Participacion" in sample:
            filas = sorted(data["series"], key=lambda r: r.get("Participacion") or 0, reverse=True)[:15]
            top = filas[0] if filas else {}
            cols = [c for c in ["Entidad", "Participacion", "IVF_2018", "Constante_2018", "Var_anual"] if c in sample]
            ultimo_val = top.get("Participacion") or top.get("Var_anual")
            valores_mapa = {r["Entidad"]: r.get("Participacion") for r in data["series"]}
            tile_unidad = "%"
            tile_palette = "teal"
            tile_pos, tile_neg = "mayor partic.", "menor partic."
        else:
            filas = sorted(data["series"], key=lambda r: r.get("Var_anual") if r.get("Var_anual") is not None else -9999, reverse=True)[:15]
            top = filas[0] if filas else {}
            cols = ["Entidad", "Var_anual"]
            ultimo_val = top.get("Var_anual")
            valores_mapa = {r["Entidad"]: r.get("Var_anual") for r in data["series"]}
            tile_unidad = "%"
            tile_palette = "diverging"
            tile_pos, tile_neg = "mayor crec.", "menor crec."
        tile_svg = build_tile_grid_svg(valores_mapa, unidad=tile_unidad, palette=tile_palette,
                                        diverging_at_zero=(tile_palette == "diverging"),
                                        label_positivo=tile_pos, label_negativo=tile_neg)
        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": filas,
            "coloreable_cols": ["Var_anual"] if "Var_anual" in cols else [],
            "ultimo": ultimo_val,
            "delta": None, "ma12_ult": None, "alerta": "neutro",
            "_label_tabla": "Entidad líder por participación PIB" if "Participacion" in sample else "Entidad con mayor crecimiento",
            "_periodo_tabular": data.get("periodo_referencia") or "2024",
            "_top_concepto": top.get("Entidad"),
            "_chart_tipo": "bar_horizontal",
            "_tile_map_svg": tile_svg,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get(id_),
        }}
    if id_ == "itaee_estatal":
        from tile_map import build_tile_grid_svg
        sample = (data["series"][0] if data.get("series") else {}) or {}
        cols_avail = [c for c in ("Var_anual", "Var_trimestral", "Indice_desest") if c in sample]
        sort_key = "Var_anual" if "Var_anual" in cols_avail else (cols_avail[0] if cols_avail else None)
        filas = sorted(data["series"], key=lambda r: r.get(sort_key) if r.get(sort_key) is not None else -9999, reverse=True)[:15] if sort_key else data.get("series", [])[:15]
        top = filas[0] if filas else {}
        cols = ["Entidad"] + cols_avail
        # Tile map por var anual
        valores_mapa = {r["Entidad"]: r.get(sort_key) for r in data.get("series", [])}
        is_diverging = any((v is not None and v < 0) for v in valores_mapa.values())
        tile_svg = build_tile_grid_svg(valores_mapa, unidad="%",
                                        palette="diverging" if is_diverging else "teal",
                                        diverging_at_zero=is_diverging,
                                        label_positivo="mayor crec.", label_negativo="caída")
        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": filas,
            "coloreable_cols": [c for c in ("Var_anual", "Var_trimestral") if c in cols],
            "ultimo": top.get(sort_key) if sort_key else None,
            "delta": None, "ma12_ult": None, "alerta": "neutro",
            "_label_tabla": "ITAEE líder trimestral",
            "_periodo_tabular": data.get("periodo_referencia") or "T4-25",
            "_top_concepto": top.get("Entidad"),
            "_chart_tipo": "bar_horizontal",
            "_bar_diverging": True,
            "_bar_sort_key": sort_key,
            "_tile_map_svg": tile_svg,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get(id_),
        }}
    if id_ == "imai_estatal":
        from tile_map import build_tile_grid_svg
        sample = (data["series"][0] if data.get("series") else {}) or {}
        cols_avail = [c for c in ("Var_anual", "Var_mensual", "Indice_secundarias", "Indice_manufacturas") if c in sample]
        sort_key = "Indice_secundarias" if "Indice_secundarias" in cols_avail else ("Var_anual" if "Var_anual" in cols_avail else (cols_avail[0] if cols_avail else None))
        filas = sorted(data["series"], key=lambda r: r.get(sort_key) if r.get(sort_key) is not None else -9999, reverse=True)[:15] if sort_key else data.get("series", [])[:15]
        top = filas[0] if filas else {}
        cols = ["Entidad"] + cols_avail
        valores_mapa = {r["Entidad"]: r.get(sort_key) for r in data.get("series", [])}
        is_diverging = any((v is not None and v < 0) for v in valores_mapa.values())
        tile_svg = build_tile_grid_svg(valores_mapa, unidad="" if "Indice" in (sort_key or "") else "%",
                                        palette="diverging" if is_diverging else "teal",
                                        diverging_at_zero=is_diverging,
                                        label_positivo="mayor", label_negativo="menor")
        return {**base, **{
            "columnas": cols,
            "columnas_display": [friendly_col(c) for c in cols],
            "filas": filas,
            "coloreable_cols": [c for c in ("Var_anual", "Var_mensual") if c in cols],
            "ultimo": top.get(sort_key) if sort_key else None,
            "delta": None, "ma12_ult": None, "alerta": "neutro",
            "_label_tabla": "IMAI estatal líder",
            "_periodo_tabular": data.get("periodo_referencia") or "feb-26",
            "_top_concepto": top.get("Entidad"),
            "_chart_tipo": "bar_grouped_horizontal",
            "_tile_map_svg": tile_svg,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get(id_),
        }}

    if id_ == "empleo_imss":
        from tile_map import build_tile_grid_svg
        series          = data.get("series", [])
        s_sector        = data.get("series_sector", [])
        s_entidad       = data.get("series_entidad", [])
        nac_yoy         = data.get("series_nacional_yoy", {})
        sector_yoy      = data.get("series_sector_yoy", {})
        periodo_ref     = data.get("periodo_referencia", "")
        # Nuevos campos del ingest_imss ampliado (C):
        genero_sector   = data.get("genero_por_sector", []) or []
        top_alza        = data.get("top_subsectores_alza", []) or []
        top_baja        = data.get("top_subsectores_baja", []) or []
        outsourcing     = data.get("serie_outsourcing_sec88", []) or []

        # ── Time series (Total, Permanentes, Eventuales) ─────────────────────
        N = min(60, len(series))
        periodos_ts  = [r["Periodo"]     for r in series[-N:]]
        serie_total  = [num(r.get("Total"))       for r in series[-N:]]
        serie_perm   = [num(r.get("Permanentes")) for r in series[-N:]]
        serie_event  = [num(r.get("Eventuales"))  for r in series[-N:]]
        serie_hombres= [num(r.get("Hombres"))     for r in series[-N:]]
        serie_mujeres= [num(r.get("Mujeres"))     for r in series[-N:]]
        ma12_ts      = compute_ma12(serie_total)

        ultimo_total = serie_total[-1] if serie_total else None
        delta_m      = data.get("_delta_mensual")
        delta_a      = data.get("_delta_anual")

        # ── Sector tabla ─────────────────────────────────────────────────────
        sector_cols  = ["Sector", "Total", "Var_mensual", "Var_anual"]
        sector_filas = sorted(s_sector, key=lambda r: r.get("Total") or 0, reverse=True)

        # ── Entidad tile map ─────────────────────────────────────────────────
        valores_mapa = {r["Entidad"]: r.get("Var_anual") for r in s_entidad}
        is_div = any(v is not None and v < 0 for v in valores_mapa.values())
        tile_svg = build_tile_grid_svg(
            valores_mapa, unidad="%", palette="diverging" if is_div else "teal",
            diverging_at_zero=is_div,
            label_positivo="mayor crec.", label_negativo="menor crec."
        )
        entidad_filas = sorted(s_entidad, key=lambda r: r.get("Total") or 0, reverse=True)

        # KPI de estructura
        perm_pct  = data.get("_permanentes_pct")
        event_pct = data.get("_eventuales_pct")
        muj_pct   = data.get("_mujeres_pct")

        # ── YoY nacional (para main chart) ──────────────────────────────────
        nac_yoy_periodos = nac_yoy.get("periodos", [])
        nac_yoy_valores  = nac_yoy.get("var_anual", [])
        nac_yoy_ult      = nac_yoy_valores[-1] if nac_yoy_valores else None

        # ── YoY por sector (para mini-charts) ────────────────────────────────
        # Ordenar sectores por Total descendente para que el grid sea coherente
        sector_order = [r["Sector"] for r in sector_filas]
        sector_yoy_ordered = {}
        for nombre in sector_order:
            if nombre in sector_yoy:
                sector_yoy_ordered[nombre] = sector_yoy[nombre]
        # Añadir los que queden sin orden explícito
        for nombre, v in sector_yoy.items():
            if nombre not in sector_yoy_ordered:
                sector_yoy_ordered[nombre] = v

        return {**base, **{
            # Time series chart (absolutos, para el chart principal heredado)
            "periodos":        periodos_ts,
            "series": {
                "Total (M)":       [round(v / 1e6, 3) if v is not None else None for v in serie_total],
                "Permanentes (M)": [round(v / 1e6, 3) if v is not None else None for v in serie_perm],
                "Eventuales (M)":  [round(v / 1e6, 3) if v is not None else None for v in serie_event],
            },
            "series_long": {
                "Total (M)":       [round(v / 1e6, 3) if v is not None else None for v in serie_total],
                "Permanentes (M)": [round(v / 1e6, 3) if v is not None else None for v in serie_perm],
                "Eventuales (M)":  [round(v / 1e6, 3) if v is not None else None for v in serie_event],
            },
            "periodos_long": periodos_ts,
            "ma12":            ma12_ts,
            "ma12_long":       ma12_ts,
            "campoDefault":    "Total (M)",
            "campoDefaultLabel": "Total (millones de puestos)",
            "ultimo":          round(ultimo_total / 1e6, 3) if ultimo_total else None,
            "delta":           delta_m,
            "delta_anual":     delta_a,
            "ma12_ult":        ma12_ts[-1] if ma12_ts else None,
            "alerta":          "neutro",
            # Sector table (snapshot último mes)
            "columnas":        sector_cols,
            "columnas_display":["Sector", "Puestos", "Δ mensual %", "Δ anual %"],
            "filas":           sector_filas,
            "coloreable_cols": ["Var_mensual", "Var_anual"],
            "_label_tabla":    "Desglose por sector económico",
            "_periodo_tabular": periodo_ref,
            # YoY histórico nacional
            "_nac_yoy_periodos": nac_yoy_periodos,
            "_nac_yoy_valores":  nac_yoy_valores,
            "_nac_yoy_ult":      round(nac_yoy_ult, 2) if nac_yoy_ult is not None else None,
            # YoY histórico por sector
            "_sector_yoy": sector_yoy_ordered,
            # Nuevos bloques C (sólo presentes si ingest_imss.py ampliado los generó)
            "_genero_sector": genero_sector,
            "_top_subsectores_alza": top_alza,
            "_top_subsectores_baja": top_baja,
            "_outsourcing_serie": outsourcing,
            # Entidad
            "_entidad_filas":   entidad_filas,
            "_entidad_cols":    ["Entidad", "Total", "Participacion", "Var_anual"],
            "_entidad_cols_display": ["Entidad", "Puestos", "Partic. %", "Δ anual %"],
            # Tile map
            "_tile_map_svg":   tile_svg,
            "_top_concepto":   entidad_filas[0]["Entidad"] if entidad_filas else None,
            # Estructura
            "_perm_pct":   perm_pct,
            "_event_pct":  event_pct,
            "_muj_pct":    muj_pct,
            "_serie_hombres": [round(v / 1e6, 3) if v is not None else None for v in serie_hombres],
            "_serie_mujeres": [round(v / 1e6, 3) if v is not None else None for v in serie_mujeres],
            "_periodos_ts":   periodos_ts,
            "interp": {"tipo": "pendiente", "mensaje": "Interpretación pendiente de próxima publicación."},
            "_metodologia": METODOLOGIA_MAP.get(id_),
        }}

    return None


_MESES_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_manual_prox(texto: str, fallback: dict) -> dict:
    """Parsea 'DD de <mes> de YYYY' y devuelve {fecha: 'D mmm YYYY', tipo: nombre original}.

    Si la fecha ya pasó, devuelve fallback (fecha del calendario ICS) para que el sitio
    siempre muestre la próxima publicación real y no una fecha stale del campo manual.
    """
    m = re.match(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", texto.strip().lower())
    if not m:
        return fallback
    dia, mes_nombre, anio = int(m.group(1)), m.group(2), m.group(3)
    mes_num = _MESES_MAP.get(mes_nombre)
    if not mes_num:
        return fallback
    fecha_iso = f"{anio}-{mes_num:02d}-{dia:02d}"
    # Si la fecha manual ya pasó, el campo está desactualizado: usar el calendario
    try:
        if date.fromisoformat(fecha_iso) < date.today():
            return fallback
    except ValueError:
        return fallback
    fecha_friendly = f"{dia} {MESES[mes_num - 1]} {anio}"
    return {"fecha": fecha_friendly, "fecha_iso": fecha_iso, "tipo": fallback.get("tipo") or "Próxima publicación INEGI"}


def load_all(project_root: Path) -> tuple[dict, dict, dict]:
    """Lee catálogo, calendar y thresholds. Devuelve indicadores normalizados + calendar + thresholds."""
    cfg_dir = project_root / "config"
    data_dir = project_root / "data"
    catalog = json.loads((cfg_dir / "indicators.json").read_text(encoding="utf-8"))["indicadores"]
    calendar = json.loads((cfg_dir / "calendar.json").read_text(encoding="utf-8")).get("indicadores", {})
    thresholds = json.loads((cfg_dir / "thresholds.json").read_text(encoding="utf-8"))["thresholds"]

    indicadores = {}
    for meta in catalog:
        obj = build_indicator(meta, data_dir, calendar, thresholds)
        if obj:
            indicadores[meta["id"]] = obj

    # Interpretaciones externas
    interp_path = data_dir / "interpretations.json"
    if interp_path.exists():
        try:
            interps = json.loads(interp_path.read_text(encoding="utf-8"))
            for iid, block in (interps or {}).items():
                if iid in indicadores and isinstance(block, dict):
                    indicadores[iid]["interp"] = block
        except Exception:
            pass

    return indicadores, calendar, thresholds
