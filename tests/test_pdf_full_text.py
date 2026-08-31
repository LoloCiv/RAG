"""El paso de grafo necesita el texto COMPLETO del PDF, sin chunkear (una
llamada a Claude por documento). Estos tests corren contra un PDF real de
sample_data -- es parseo local, sin credenciales ni servicios.
"""

import pytest

from app.config import PROJECT_ROOT
from app.ingestion.pdf_loader import load_and_chunk_pdf_bytes, load_pdf_full_text

_PDF = PROJECT_ROOT / "sample_data" / "Resumen_Evento_Casamiento_Perez_Gomez.pdf"


@pytest.fixture(scope="module")
def pdf_bytes() -> bytes:
    if not _PDF.exists():
        pytest.skip(f"falta el PDF de prueba: {_PDF}")
    return _PDF.read_bytes()


def test_devuelve_texto_no_vacio(pdf_bytes):
    texto = load_pdf_full_text(pdf_bytes, _PDF.name)
    assert texto.strip()


def test_es_un_solo_string_mas_largo_que_un_chunk(pdf_bytes):
    # La diferencia con load_and_chunk_pdf_bytes: no viene troceado.
    texto = load_pdf_full_text(pdf_bytes, _PDF.name)
    assert isinstance(texto, str)
    assert len(texto) > 500


def test_conserva_el_contenido_que_ven_los_chunks(pdf_bytes):
    # Mismo parseo de fondo: lo que aparece en el primer chunk tiene que
    # estar en el texto completo. Si el refactor rompiera uno de los dos
    # caminos, esto lo detecta.
    chunks = load_and_chunk_pdf_bytes(pdf_bytes, _PDF.name)
    texto = load_pdf_full_text(pdf_bytes, _PDF.name)
    primera_linea = chunks[0].splitlines()[0].strip()
    assert primera_linea in texto


def test_el_chunking_existente_sigue_funcionando(pdf_bytes):
    # Red de seguridad del refactor: load_and_chunk_pdf_bytes no cambia.
    chunks = load_and_chunk_pdf_bytes(pdf_bytes, _PDF.name)
    assert chunks
    assert all(isinstance(c, str) and c.strip() for c in chunks)
