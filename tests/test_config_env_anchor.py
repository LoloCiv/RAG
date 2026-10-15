"""La configuracion carga el .env desde la raiz, no desde el cwd."""

import os
import subprocess
import sys
from pathlib import Path


def test_config_loads_env_regardless_of_cwd(tmp_path):
    # Antes este test exigia una ANTHROPIC_API_KEY real en el .env, asi que
    # fallaba en cualquier clon limpio (sin .env). Lo que importa del ancla
    # es QUE RUTA recibe load_dotenv, no el contenido del archivo: se
    # intercepta la llamada en un subproceso lanzado desde otro cwd.
    project_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)

    code = (
        "import dotenv\n"
        "captured = []\n"
        "dotenv.load_dotenv = lambda *a, **k: captured.append(a[0] if a else k.get('dotenv_path'))\n"
        "from app import config\n"
        "print(captured[0])\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == project_root / ".env"


def test_queries_dir_lives_under_data_dir():
    from app import config

    assert config.QUERIES_DIR == config.DATA_DIR / "queries"
    assert config.QUERIES_DIR.exists()
