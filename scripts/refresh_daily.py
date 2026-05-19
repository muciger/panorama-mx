"""Orquesta el refresh completo del tablero. Diseñado para correr diario vía cron.

Orden de ejecución:
  1. calendar_sync.py          Refresca calendar.json desde ICS oficial INEGI
  2. bie/ingest.py             Refresca data/*.json desde API BIE-INEGI
  3. composites.py             Recalcula composites derivados
  4. generate_interpretations  Interpretaciones DeepSeek para indicadores publicados hoy
  5. build.py                  Regenera site/ con plantillas Jinja
  6. validate.py               Reporte de calidad del output
  7. (opcional) generate_synthesis.py  Síntesis macro automática con Claude

Uso:
    python3 scripts/refresh_daily.py                  # flujo completo
    python3 scripts/refresh_daily.py --skip-bie       # sin refresh API (solo recalcular)
    python3 scripts/refresh_daily.py --quiet          # solo logs WARN/ERROR
    python3 scripts/refresh_daily.py --with-claude    # incluye síntesis automática
    python3 scripts/refresh_daily.py --skip-interp    # sin generar interpretaciones

Cron sugerido (corre 8:30 am hora del centro de México, post publicación INEGI):
    30 8 * * * cd /ruta/al/proyecto && python3 scripts/refresh_daily.py >> logs/refresh.log 2>&1
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] refresh: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("refresh")


def _cargar_token() -> None:
    """Carga INEGI_BIE_TOKEN desde ~/.panorama_env si aún no está en el entorno.

    Permite correr `python3 scripts/refresh_daily.py` sin hacer
    `source ~/.panorama_env` primero. Los subprocesos heredan la variable.
    """
    if os.environ.get("INEGI_BIE_TOKEN"):
        return
    env_file = Path.home() / ".panorama_env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().removeprefix("export").strip()
        v = v.strip().strip('"').strip("'")
        if k:
            os.environ.setdefault(k, v)
    if os.environ.get("INEGI_BIE_TOKEN"):
        log.info("Token BIE cargado desde ~/.panorama_env")


def _verificar_calendar_fresco(max_dias: int = 2) -> None:
    """Verifica que config/calendar.json esté generado en los últimos max_dias.
    Solo loguea warning si está desactualizado. No aborta."""
    import json
    from datetime import date
    cal_path = ROOT / "config" / "calendar.json"
    if not cal_path.exists():
        log.warning("calendar.json NO existe después del sync")
        return
    try:
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        gen = cal.get("_generado")
        if not gen:
            log.warning("calendar.json sin campo _generado")
            return
        gen_d = date.fromisoformat(gen)
        dias = (date.today() - gen_d).days
        if dias > max_dias:
            log.warning(
                "calendar.json tiene %d días de antigüedad (>%d). "
                "Verifica que calendar_sync se haya ejecutado correctamente.",
                dias, max_dias
            )
        else:
            log.info("    calendar.json fresco · generado %s (%d días)", gen, dias)
    except Exception as exc:
        log.warning("No pude verificar frescura del calendar: %s", exc)


def run_step(label: str, cmd: list[str], optional: bool = False) -> bool:
    """Corre un subcomando y reporta tiempo. Devuelve True si OK, False si falla."""
    log.info("→ %s", label)
    t0 = time.time()
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1200)
    except subprocess.TimeoutExpired:
        log.error("✗ %s TIMEOUT (>1200s)", label)
        return False
    dt = time.time() - t0
    if result.returncode != 0:
        # Imprime stderr completo a stdout para que aparezca en el log del workflow
        if optional:
            log.warning("⚠ %s falló (opcional, continúa)", label)
        else:
            log.error("✗ %s FAIL en %.1fs", label, dt)
        if result.stderr:
            print("--- STDERR ---")
            print(result.stderr)
            print("--- END STDERR ---")
        if result.stdout:
            print("--- STDOUT ---")
            print(result.stdout)
            print("--- END STDOUT ---")
        return False
    # Mostrar últimas líneas relevantes del stdout
    last_lines = [l for l in result.stdout.strip().splitlines() if l.strip()][-3:]
    if last_lines:
        for ln in last_lines:
            log.info("    %s", ln)
    log.info("✓ %s OK en %.1fs", label, dt)
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skip-bie", action="store_true", help="No refrescar datos desde API BIE")
    p.add_argument("--skip-calendar", action="store_true", help="No actualizar calendar.json desde ICS")
    p.add_argument("--skip-interp", action="store_true", help="No generar interpretaciones DeepSeek")
    p.add_argument("--with-claude", action="store_true", help="Generar home_synthesis.json con Claude API")
    p.add_argument("--quiet", action="store_true", help="Solo logs WARN/ERROR")
    args = p.parse_args(argv)

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    _cargar_token()
    log.info("=== refresh diario · %s ===", time.strftime("%Y-%m-%d %H:%M:%S"))
    t_start = time.time()
    pass_count = 0
    fail_count = 0       # fallas críticas (bloquean exit 0)
    soft_fail_count = 0  # fallas opcionales (no bloquean exit 0)

    # 1. Calendar sync (CRÍTICO: si falla, el reporte semanal queda desactualizado).
    # calendar_sync.py maneja internamente fallas de red usando cache existente,
    # solo retorna error si no hay cache disponible.
    if not args.skip_calendar:
        ok = run_step("calendar_sync (ICS oficial)", [sys.executable, str(SCRIPTS / "calendar_sync.py")])
        pass_count += int(ok)
        fail_count += int(not ok)
        if not ok:
            log.error("ABORTO: calendar_sync falló (sin cache ICS). No se construye ni deploya con calendario stale.")
            return 1
        _verificar_calendar_fresco()

    # 2. Ingest BIE
    if not args.skip_bie:
        ok = run_step("bie/ingest (32 indicadores)", [sys.executable, str(SCRIPTS / "bie" / "ingest.py")])
        pass_count += int(ok)
        fail_count += int(not ok)
        if not ok:
            log.error("ABORTO: bie/ingest falló. No se construye ni deploya con data potencialmente incompleta.")
            return 1

    # 3. Composites derivados
    ok = run_step("composites (5 derivados)", [sys.executable, str(SCRIPTS / "composites.py")])
    pass_count += int(ok)
    fail_count += int(not ok)
    if not ok:
        log.error("ABORTO: composites falló. No se construye ni deploya con derivados stale.")
        return 1

    # 4. Interpretaciones DeepSeek (solo indicadores con nueva publicación) — opcional
    if not args.skip_interp:
        interp_script = SCRIPTS / "generate_interpretations.py"
        if interp_script.exists():
            ok = run_step(
                "interpretaciones DeepSeek (indicadores publicados hoy)",
                [sys.executable, str(interp_script)],
                optional=True,
            )
            pass_count += int(ok)
            soft_fail_count += int(not ok)
        else:
            log.warning("generate_interpretations.py no existe, saltando")

    # 5. Síntesis Claude (opcional)
    if args.with_claude:
        synth_script = SCRIPTS / "generate_synthesis.py"
        if synth_script.exists():
            ok = run_step("síntesis Claude (home_synthesis.json)", [sys.executable, str(synth_script)], optional=True)
            pass_count += int(ok)
            fail_count += int(not ok)
        else:
            log.warning("generate_synthesis.py no existe, saltando")

    # 6. Build site
    ok = run_step("build (site/)", [sys.executable, str(SCRIPTS / "build.py")])
    pass_count += int(ok)
    fail_count += int(not ok)
    if not ok:
        log.error("ABORTO: build falló. site/ no es confiable, no se deploya.")
        return 1

    # 7. Validate (auditoría, no bloquea deploy si hay errors)
    ok = run_step("validate (calidad)", [sys.executable, str(SCRIPTS / "validate.py")], optional=True)
    pass_count += int(ok)
    soft_fail_count += int(not ok)

    dt = time.time() - t_start
    log.info(
        "=== Refresh completo · %d pasos OK, %d fallos críticos, %d fallos opcionales · %.1fs ===",
        pass_count, fail_count, soft_fail_count, dt,
    )
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
