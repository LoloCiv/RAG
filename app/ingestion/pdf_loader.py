"""Chunking de PDFs. Adaptado de data_loader.py del repo de referencia
(ProductionGradeRAGPythonApp) -- misma libreria (LlamaIndex) y mismos
parametros de chunking, solo que ahora recibe los bytes ya bajados de Drive
en vez de asumir un path local fijo.
"""

import logging

from llama_index.core.node_parser import SentenceSplitter
from llama_index.readers.file import PDFReader

from app.config import CHUNK_OVERLAP, CHUNK_SIZE, DOWNLOADS_DIR

logger = logging.getLogger(__name__)

_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def _extract_page_texts(pdf_bytes: bytes, file_name: str) -> list[str]:
    """Parseo crudo del PDF -> un texto por pagina.

    Extraido para que los dos consumidores (chunks para Qdrant, texto
    completo para el grafo) compartan exactamente el mismo parseo.
    """
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in file_name)
    tmp_path = DOWNLOADS_DIR / safe_name
    tmp_path.write_bytes(pdf_bytes)

    docs = PDFReader().load_data(file=tmp_path)
    return [d.text for d in docs if getattr(d, "text", None)]


def load_and_chunk_pdf_bytes(pdf_bytes: bytes, file_name: str) -> list[str]:
    """Escribe los bytes a un archivo temporal en downloads/ (PDFReader de
    LlamaIndex necesita un path, no acepta bytes en memoria) y devuelve la
    lista de chunks de texto.
    """
    texts = _extract_page_texts(pdf_bytes, file_name)

    chunks: list[str] = []
    for text in texts:
        chunks.extend(_splitter.split_text(text))

    logger.info("PDF %s -> %d chunks", file_name, len(chunks))
    return chunks


def load_pdf_full_text(pdf_bytes: bytes, file_name: str) -> str:
    """Texto completo sin chunkear, para el paso de grafo (una llamada a
    Claude por documento entero -- ver app/graph/ingest.py).

    Esto parsea el PDF una segunda vez por resync. Es un trade-off aceptado:
    el parseo es local y barato, y la alternativa (cachear el resultado
    entre los dos caminos) acoplaria el pipeline vectorial al de grafo.
    """
    return "\n\n".join(_extract_page_texts(pdf_bytes, file_name))
