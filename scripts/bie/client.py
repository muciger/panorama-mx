"""
INEGI BIE API Client
Wrapper para la API de Indicadores del Banco de Información Económica (BIE) v2.0
Docs: https://www.inegi.org.mx/servicios/api_indicadores.html
"""

import requests
from typing import Optional


BASE_URL = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml"

# Fuentes disponibles confirmadas desde el Constructor de Consultas
FUENTES = {
    "demografía": "BISE",       # Banco de Indicadores (población, educación, salud)
    "economía": "BIE-BISE",     # Banco de Información Económica (IGAE, PIB, inflación, empleo)
}

# Mapeo curado de indicadores del BIE.
# Fuente primaria: Lista oficial de feeds del INEGI (feeds.html) + Constructor de Consultas.
# Para cada indicador se incluyen la serie original y, cuando existe,
# la serie de variación y la serie desestacionalizada.
INDICADORES_BIE = {
    # ---------------------------------------------------------------------------
    # IGAE - Indicador Global de la Actividad Económica (mensual, base 2018)
    # ---------------------------------------------------------------------------
    "igae_total":                    "737121",  # Índice, series originales, total
    "igae_total_variacion":          "737145",  # Variación mensual
    "igae_total_desest":             "737219",  # Serie desestacionalizada
    "igae_actividades_primarias":    "737096",
    "igae_actividades_secundarias":  "737104",
    "igae_actividades_terciarias":   "737115",

    # ---------------------------------------------------------------------------
    # PIB - Producto Interno Bruto (trimestral)
    # ---------------------------------------------------------------------------
    "pib_vol_2018_trimestral":       "735879",  # Vol. físico a precios 2018
    "pib_variacion_anual":           "735904",  # Variación anual (%) — total
    "pib_desest_trimestral":         "736181",  # Desestacionalizado
    "pib_precios_corrientes":        "735979",  # A precios corrientes (trim)
    "pib_precios_corrientes_valor":  "734407",  # Valores absolutos corrientes
    "pib_anual_vol_2018":            "782389",  # Anual a precios 2018
    "pib_desest_eo":                 "736183",  # Estimación oportuna desest
    "pib_desest_trim":               "736182",  # Desest. trimestral
    # Variación anual por actividad (precios 2018, Series Originales)
    "pib_var_primarias":             "735907",
    "pib_var_secundarias":           "735908",
    "pib_var_mineria":               "735909",
    "pib_var_energia_agua_gas":      "735910",
    "pib_var_construccion":          "735911",
    "pib_var_manufacturas":          "735912",
    "pib_var_terciarias":            "735913",
    "pib_var_comercio_mayor":        "735914",
    "pib_var_comercio_menor":        "735915",
    "pib_var_transportes":           "735916",
    "pib_var_financieros":           "735918",
    "pib_var_inmobiliarios":         "735919",
    "pib_var_profesionales":         "735920",
    "pib_var_gubernamentales":       "735928",
    # QoQ desestacionalizado por actividad
    "pib_desest_qoq_total":          "736185",
    "pib_desest_qoq_primarias":      "736196",
    "pib_desest_qoq_secundarias":    "736203",
    "pib_desest_qoq_terciarias":     "736210",

    # ---------------------------------------------------------------------------
    # INPC - Índice Nacional de Precios al Consumidor / Inflación
    # ---------------------------------------------------------------------------
    "inpc_inflacion_mensual":        "910399",  # Variación mensual
    "inpc_inflacion_mensual_sub":    "910400",  # Mensual subyacente
    "inpc_inflacion_anual":          "910406",  # Variación anual
    "inpc_inflacion_anual_sub":      "910407",  # Anual subyacente
    "inpc_inflacion_acumulada":      "910413",  # Acumulada en el año
    "inpc_inflacion_acumul_sub":     "910414",  # Acumulada subyacente
    "inpc_quincenal":                "910427",  # Variación quincenal
    "inpc_quincenal_sub":            "910428",  # Quincenal subyacente
    "inpc_quincenal_interanual":     "910438",  # Quincenal interanual
    "inpc_quincenal_interanual_sub": "910439",  # Quincenal interanual sub

    # ---------------------------------------------------------------------------
    # Actividad industrial (mensual, base 2018)
    # ---------------------------------------------------------------------------
    "actind_total":                  "736407",  # Índice volumen físico, total
    "actind_variacion":              "736526",  # Variación
    "actind_desest":                 "736885",  # Desestacionalizado
    "manufactureras_variacion_anual":"736537",  # Manufactura var. anual

    # ---------------------------------------------------------------------------
    # Sector externo
    # ---------------------------------------------------------------------------
    "balanza_comercial_saldo":       "897",     # Saldo balanza comercial
    "balanza_comercial_desest":      "87537",   # Saldo desestacionalizado

    # ---------------------------------------------------------------------------
    # Mercado laboral (ENOE)
    # ---------------------------------------------------------------------------
    "tasa_desocupacion":             "444883",  # Tasa de desocupación mensual
    "tasa_desocupacion_desest":      "444884",  # Desestacionalizada

    # ---------------------------------------------------------------------------
    # Demanda interna / consumo
    # ---------------------------------------------------------------------------
    "consumo_privado_var_anual":     "740946",  # IMCPMI variación anual
    "ventas_menudeo":                "718506",  # Ventas al por menor
    "ventas_menudeo_var":            "718507",  # Variación
    "ventas_menudeo_desest":         "718942",  # Desestacionalizado
    "confianza_consumidor":          "454168",  # ICC mensual
    "confianza_consumidor_desest":   "454186",  # Desestacionalizado

    # ---------------------------------------------------------------------------
    # Inversión
    # ---------------------------------------------------------------------------
    "fbcf_total":                    "741020",  # Formación bruta capital fijo
    "fbcf_variacion":                "741040",  # Variación
    "fbcf_desest":                   "741100",  # Desestacionalizado

    # ---------------------------------------------------------------------------
    # Oferta y demanda global
    # ---------------------------------------------------------------------------
    "odgbs_total":                   "737371",  # Oferta y demanda global
    "odgbs_variacion":               "737374",
    "odgbs_desest":                  "737445",

    # ---------------------------------------------------------------------------
    # IMMEX y manufactura
    # ---------------------------------------------------------------------------
    "immex_personal_ocupado":        "203933",

    # ---------------------------------------------------------------------------
    # Minería y metalurgia
    # ---------------------------------------------------------------------------
    "mineria_total":                 "656",
    "mineria_variacion":             "657",
    "mineria_desest":                "661524",
    "cobre_produccion":              "666",
    "oro_produccion":                "659",
    "plata_produccion":              "660",

    # ---------------------------------------------------------------------------
    # Indicadores cíclicos
    # ---------------------------------------------------------------------------
    "indicador_adelantado":          "214308",

    # ---------------------------------------------------------------------------
    # Gobierno
    # ---------------------------------------------------------------------------
    "consumo_gobierno_total":        "728658",  # Consumo gobierno a precios 2018 (anual)

    # ---------------------------------------------------------------------------
    # INPP - Índice Nacional de Precios al Productor (mensual)
    # Tema BIE: 3623 > 3790
    # ---------------------------------------------------------------------------
    "inpp_indice_total":             "1700001",  # INPP Mercancías y Servicios Finales
    "inpp_indice_con_petroleo":      "1700002",  # INPP con Petróleo y con Servicios
    "inpp_manufactureras":           "1700244",  # 31-33 Industrias manufactureras
    "inpp_variacion_sin_petroleo":   "1800001",  # Variación mensual sin petróleo
    "inpp_variacion_con_petroleo":   "1800002",  # Variación mensual con petróleo

    # ---------------------------------------------------------------------------
    # EMOE - Encuesta Mensual de Opinión Empresarial (mensual, base 2018)
    # Tema BIE: 138032
    # ---------------------------------------------------------------------------
    "emoe_iat_manufacturero":        "701490",   # IAT total industrias manufactureras
    "emoe_ice_manufacturero":        "701570",   # ICE total industrias manufactureras
    "emoe_ipm_manufacturero":        "701618",   # IPM total industrias manufactureras

    # ---------------------------------------------------------------------------
    # EMIM - Encuesta Mensual Industria Manufacturera (mensual, base 2018)
    # Tema BIE: 542904
    # ---------------------------------------------------------------------------
    "emim_personal_orig":            "702139",   # Personal ocupado total (orig)
    "emim_ivf_desest":               "910466",   # IVF producción total (desest)
    "emim_ivf_variacion_desest":     "910467",   # Variación anual IVF (desest)

    # ---------------------------------------------------------------------------
    # ENEC - Encuesta Nacional de Empresas Constructoras (mensual, base 2018)
    # Tema BIE: 568505
    # ---------------------------------------------------------------------------
    "enec_valor_prod_orig":          "720322",   # Valor producción total (orig)
    "enec_valor_prod_desest":        "720346",   # Valor producción total (desest)

    # ---------------------------------------------------------------------------
    # EMS - Encuesta Mensual de Servicios (mensual, base 2018)
    # Tema BIE: 564077
    # ---------------------------------------------------------------------------
    "ems_ingresos_orig":             "715722",   # Ingresos totales (orig)
    "ems_ingresos_desest":           "715854",   # Ingresos totales (desest)

    # ---------------------------------------------------------------------------
    # EMEC - Encuesta Mensual sobre Empresas Comerciales (mensual, base 2018)
    # Tema BIE: 562654
    # ---------------------------------------------------------------------------
    "emec_mayoreo_orig":             "718480",   # Comercio al por mayor (orig)
    "emec_mayoreo_desest":           "718520",   # Comercio al por mayor (desest)

    # ---------------------------------------------------------------------------
    # ENOE trimestral (15 años y más)
    # Tema BIE: 123
    # ---------------------------------------------------------------------------
    "enoe_pea_total":                "289244",   # PEA total
    "enoe_pea_ocupada":              "289245",   # PEA ocupada
    "enoe_pea_desocupada":           "289246",   # PEA desocupada
    "enoe_desocupada_total":         "289289",   # Población desocupada total

    # ---------------------------------------------------------------------------
    # ITAEE - Indicador Trimestral Actividad Económica Estatal (trim, base 2018)
    # Tema BIE: 603944
    # IMPORTANTE: requiere geo estatal ('01'-'32'). No existe total nacional (geo='00').
    # Verificado: geo='09' (CDMX) y geo='14' (Jalisco) devuelven datos.
    # No todos los estados tienen cobertura en todos los periodos.
    # ---------------------------------------------------------------------------
    "itaee_indice":                  "741177",   # Índice total por estado
    "itaee_con_petroleo":            "741180",   # Con petróleo por estado
    "itaee_sin_petroleo":            "741181",   # Sin petróleo por estado

    # ---------------------------------------------------------------------------
    # IMAI - Indicador Mensual Actividad Industrial Estatal (mensual, base 2018)
    # Tema BIE: 607220 | Usar geo='01'-'32' para entidades federativas
    # ---------------------------------------------------------------------------
    "imai_total_nacional":           "738182",   # Total actividades secundarias
    "imai_manufacturera_total":      "736418",   # Total industrias manufactureras

    # ---------------------------------------------------------------------------
    # Subsector automotriz (IVF mensual, base 2018)
    # Nota: BIE no separa ligeros/pesados; usa 736512 para automóviles y camiones
    # ---------------------------------------------------------------------------
    "actind_automotriz_total":       "736511",   # Subsector 336 total equipo transporte
    "actind_automoviles_camiones":   "736512",   # 3361 Fabricación automóviles y camiones

    # ---------------------------------------------------------------------------
    # PIB por entidad federativa (anual, base 2018)
    # Tema BIE: 610708 | geo='00' funciona para total nacional; geo='01'-'32' por estado
    # ---------------------------------------------------------------------------
    "pib_estatal_constante":         "746097",   # A precios constantes 2018
    "pib_estatal_corriente":         "750453",   # A precios corrientes
    "pib_estatal_ivf":               "749001",   # Índice de volumen físico 2018=100
    "pib_estatal_participacion":     "747549",   # Participación porcentual (constantes)

    # ---------------------------------------------------------------------------
    # Exportaciones por entidad federativa
    # Tema BIE: 38035 (trimestral), 38068 (anual)
    # IMPORTANTE: solo funciona con geo='01'-'32'. geo='00' devuelve 400.
    # ---------------------------------------------------------------------------
    "export_entidad_trimestral":     "629659",   # Exportaciones totales, trimestral
    "export_entidad_anual":          "630459",   # Exportaciones totales, anual

    # ---------------------------------------------------------------------------
    # Demografía (fuente BISE, usar fuente="BISE" al consultar)
    # ---------------------------------------------------------------------------
    "poblacion_total":               "1002000001",
}

CATALOGOS_VALIDOS = {
    "CL_INDICATOR",
    "CL_UNIT",
    "CL_NOTE",
    "CL_SOURCE",
    "CL_TOPIC",
    "CL_FREQ",
    "CL_GEO_AREA",
    "CL_STATUS",
}

# Claves geográficas comunes
GEO = {
    "nacional": "00",
    "aguascalientes": "01",
    "baja_california": "02",
    "baja_california_sur": "03",
    "campeche": "04",
    "coahuila": "05",
    "colima": "06",
    "chiapas": "07",
    "chihuahua": "08",
    "cdmx": "09",
    "durango": "10",
    "guanajuato": "11",
    "guerrero": "12",
    "hidalgo": "13",
    "jalisco": "14",
    "edomex": "15",
    "michoacan": "16",
    "morelos": "17",
    "nayarit": "18",
    "nuevo_leon": "19",
    "oaxaca": "20",
    "puebla": "21",
    "queretaro": "22",
    "quintana_roo": "23",
    "san_luis_potosi": "24",
    "sinaloa": "25",
    "sonora": "26",
    "tabasco": "27",
    "tamaulipas": "28",
    "tlaxcala": "29",
    "veracruz": "30",
    "yucatan": "31",
    "zacatecas": "32",
}


class INEGIBIEClient:
    """
    Cliente para la API del BIE del INEGI.
    token: UUID obtenido en https://www.inegi.org.mx/app/desarrolladores/generatoken/
    """

    def __init__(self, token: str, lang: str = "es", fuente: str = "BIE-BISE"):
        self.token = token
        self.lang = lang
        self.fuente = fuente

    def _redact(self, msg: str) -> str:
        """Quita el token de mensajes de error/URLs. El token va en el path de la
        URL del BIE; sin esto se filtraría a los logs de GitHub Actions."""
        return msg.replace(self.token, "***") if self.token else msg

    def get_indicator(
        self,
        indicator_id: str,
        geo: str = "00",
        recent_only: bool = False,
    ) -> dict:
        """
        Obtiene la serie de tiempo de un indicador del BIE.

        Args:
            indicator_id: Clave del indicador (ej. "1002000001" para población total)
            geo: Clave geográfica ("00" = nacional, "01"-"32" = entidad federativa)
            recent_only: True para solo el dato más reciente; False para la serie completa

        Returns:
            Dict con Header y Series (incluyendo OBSERVATIONS)
        """
        recent_str = "true" if recent_only else "false"
        url = (
            f"{BASE_URL}/INDICATOR/{indicator_id}/{self.lang}/{geo}"
            f"/{recent_str}/{self.fuente}/2.0/{self.token}?type=json"
        )
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"BIE request falló: {self._redact(str(e))}") from None

    def get_catalog(
        self,
        catalog: str,
        catalog_id: Optional[str] = None,
    ) -> dict:
        """
        Obtiene un catálogo de metadatos del BIE.

        Args:
            catalog: Tipo de catálogo. Valores válidos:
                     CL_INDICATOR, CL_UNIT, CL_NOTE, CL_SOURCE,
                     CL_TOPIC, CL_FREQ, CL_GEO_AREA, CL_STATUS
            catalog_id: ID del registro (o lista separada por comas).
                        None retorna todos los registros.

        Returns:
            Dict con CODE[] conteniendo value y Description
        """
        if catalog not in CATALOGOS_VALIDOS:
            raise ValueError(
                f"Catálogo inválido: {catalog}. "
                f"Opciones: {', '.join(sorted(CATALOGOS_VALIDOS))}"
            )
        id_str = catalog_id if catalog_id else "null"
        url = (
            f"{BASE_URL}/{catalog}/{id_str}/{self.lang}"
            f"/{self.fuente}/2.0/{self.token}?type=json"
        )
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"BIE request falló: {self._redact(str(e))}") from None

    def parse_series(self, response: dict) -> list[dict]:
        """
        Extrae las observaciones de una respuesta del endpoint INDICATOR.

        Returns:
            Lista de dicts con keys: indicator_id, freq, unit, time_period,
            obs_value, geo, last_update
        """
        rows = []
        for series in response.get("Series", []):
            indicator_id = series.get("INDICADOR")
            freq = series.get("FREQ")
            unit = series.get("UNIT")
            last_update = series.get("LASTUPDATE")
            for obs in series.get("OBSERVATIONS", []):
                rows.append({
                    "indicator_id": indicator_id,
                    "freq": freq,
                    "unit": unit,
                    "last_update": last_update,
                    "time_period": obs.get("TIME_PERIOD"),
                    "obs_value": obs.get("OBS_VALUE"),
                    "geo": obs.get("COBER_GEO"),
                })
        # La API devuelve el dato más reciente primero; revertir para orden cronológico
        rows.reverse()
        return rows
