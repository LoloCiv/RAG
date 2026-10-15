"""Entrada de Streamlit: coordinación actual e investigación histórica."""

from app.logging_conf import setup_logging
from app.ui.shell import render_app

setup_logging()
render_app()
