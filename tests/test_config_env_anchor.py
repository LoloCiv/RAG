"""La configuracion carga el .env desde la raiz, no desde el cwd."""

import os
import subprocess
import sys
from pathlib import Path


def test_config_loads_env_regardless_of_cwd(tmp_path):
    project_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env["PYTHONPATH"] = str(project_root)

    result = subprocess.run(
        [sys.executable, "-c", "from app.config import ANTHROPIC_API_KEY; print(bool(ANTHROPIC_API_KEY))"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.stdout.strip() == "True", result.stderr


def test_queries_dir_lives_under_data_dir():
    from app import config

    assert config.QUERIES_DIR == config.DATA_DIR / "queries"
    assert config.QUERIES_DIR.exists()
