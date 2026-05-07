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


def run_step(label: str, cmd: list[str], optional: bool = False) -> bool:
    """Corre un subcomando y reporta tiempo. Devuelve True si OK, False si falla."""
    log.info("→ %s", label)
    t0 = time.time()
    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        log.error("✗ %s TIMEOUT (>600s)", label)
        return False
    dt = time.time() - t0
    if result.returncode != 0:
        if optional:
            log.warning("⚠ %s falló (opcional, continúa)\n%s", label, result.stderr.strip()[:500])
            return False
        log.error("✗ %s FAIL en %.1fs\n%s", label, dt, result.stderr.strip()[:500])
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

    log.info("=== refresh diario · %s ===", time.strftime("%Y-%m-%d %H:%M:%S"))
    t_start = time.time()
    pass_count = 0
    fail_count = 0

    # 1. Calendar sync
    if not args.skip_calendar:
        ok = run_step("calendar_sync (ICS oficial)", [sys.executable, str(SCRIPTS / "calendar_sync.py")], optional=True)
        pass_count += int(ok)
        fail_count += int(not ok)

    # 2. Ingest BIE
    if not args.skip_bie:
        ok = run_step("bie/ingest (32 indicadores)", [sys.executable, str(SCRIPTS / "bie" / "ingest.py")])
        pass_count += int(ok)
        fail_count += int(not ok)

    # 3. Composites derivados
    ok = run_step("composites (5 derivados)", [sys.executable, str(SCRIPTS / "composites.py")])
    pass_count += int(ok)
    fail_count += int(not ok)

    # 4. Interpretaciones DeepSeek (solo indicadores con nueva publicación)
    if not args.skip_interp:
        interp_script = SCRIPTS / "generate_interpretations.py"
        if interp_script.exists():
            ok = run_step(
                "interpretaciones DeepSeek (indicadores publicados hoy)",
                [sys.executable, str(interp_script)],
                optional=True,
            )
            pass_count += int(ok)
            fail_count += int(not ok)
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

    # 7. Validate
    ok = run_step("validate (calidad)", [sys.executable, str(SCRIPTS / "validate.py")])
    pass_count += int(ok)
    fail_count += int(not ok)

    dt = time.time() - t_start
    log.info("=== Refresh completo · %d pasos OK, %d fallos · %.1fs ===", pass_count, fail_count, dt)
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
