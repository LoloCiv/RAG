"""Chunking de Google Docs nativos. Mismo splitter que pdf_loader.py --
la unica diferencia real con un PDF es como se obtiene el texto (export a
texto plano via la Drive API, en vez de parsear un PDF).
"""

import logging

from llama_index.core.node_parser import SentenceSplitter

from app.config import CHUNK_OVERLAP, CHUNK_SIZE

logger = logging.getLogger(__name__)

_splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def chunk_gdoc_text(text: str, file_name: str) -> list[str]:
    chunks = _splitter.split_text(text)
    logger.info("Google Doc %s -> %d chunks", file_name, len(chunks))
    return chunks
