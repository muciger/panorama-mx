"""Defensa anti-borrado de data/*.json para el deploy en cloud.

Compara, por número de registros (no por líneas, que son sensibles a reformateo),
cada data/*.json del working tree contra un ref base (por defecto HEAD~1) y aborta
si algún archivo desapareció, quedó ilegible o perdió >50% de registros.

Esto es defensa en profundidad. La guarda primaria vive en scripts/bie/ingest.py
(guarda_segura), que impide la escritura destructiva antes del commit. Este check
solo evita deployar un commit ya malo.

Uso:
    python3 scripts/ci_sanity_check.py [ref_base]   # ref_base por defecto: HEAD~1

Exit 0 si todo OK · Exit 1 si hubo cambio destructivo · Exit 2 si error de setup.
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UMBRAL_MIN_REGISTROS = 4  # archivos chicos no disparan el chequeo de encogimiento


def git_show(ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{path}"],
                        capture_output=True, text=True, cwd=ROOT)
    return r.stdout if r.returncode == 0 else None


def registros(txt: str | None) -> int | None:
    """None = inexistente · -1 = JSON ilegible · >=0 = nº de registros."""
    if txt is None:
        return None
    try:
        d = json.loads(txt)
    except Exception:
        return -1
    s = d.get("series")
    if isinstance(s, list):
        return len(s)
    p = d.get("periodos")
    return len(p) if isinstance(p, list) else 0


def main(argv: list[str]) -> int:
    ref = argv[1] if len(argv) > 1 else "HEAD~1"

    if subprocess.run(["git", "rev-parse", "--verify", ref],
                      capture_output=True, cwd=ROOT).returncode != 0:
        print(f"ERROR: el ref base '{ref}' no existe (fetch-depth insuficiente). "
              "El sanity check no puede comparar.", file=sys.stderr)
        return 2

    old_list = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", "data"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout.split()
    old_files = {f for f in old_list if f.endswith(".json")}
    new_files = {str(Path(p).as_posix()) for p in glob.glob("data/*.json")}

    fallas: list[str] = []
    for f in sorted(old_files | new_files):
        old_n = registros(git_show(ref, f))
        try:
            new_n = registros((ROOT / f).read_text(encoding="utf-8"))
        except FileNotFoundError:
            new_n = None

        if old_n is None:
            # Archivo nuevo: solo exigimos que traiga datos legibles.
            if new_n in (None, 0, -1):
                fallas.append(f"{f}: archivo nuevo vacío o ilegible")
            continue
        if new_n is None:
            fallas.append(f"{f}: ELIMINADO (en {ref} tenía {old_n} registros)")
        elif new_n == -1:
            fallas.append(f"{f}: JSON ilegible en el working tree")
        elif old_n >= UMBRAL_MIN_REGISTROS and new_n < old_n * 0.5:
            fallas.append(f"{f}: registros {old_n} -> {new_n} (>50% perdido)")

    if fallas:
        print("ABORTO · data/ sufrió cambios destructivos vs", ref)
        for x in fallas:
            print("  -", x)
        return 1

    print(f"Sanity check OK · ningún data/*.json perdió registros vs {ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
