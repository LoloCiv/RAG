from app.ingestion.source_id import (
    pdf_or_doc_source_id,
    sheet_tab_source_id,
    table_blob_point_id,
    text_chunk_point_id,
)


def test_pdf_or_doc_source_id_shape():
    assert pdf_or_doc_source_id("abc123") == "gdrive:abc123"


def test_sheet_tab_source_id_shape():
    assert sheet_tab_source_id("abc123", "Proveedores") == "gdrive:abc123:Proveedores"


def test_text_chunk_point_id_is_deterministic():
    # Idempotencia: mismo source_id + indice -> siempre el mismo point id
    # (es lo que hace que re-ingerir un archivo sin cambios no duplique
    # puntos en Qdrant).
    id1 = text_chunk_point_id("gdrive:abc123", 0)
    id2 = text_chunk_point_id("gdrive:abc123", 0)
    assert id1 == id2


def test_text_chunk_point_id_differs_by_index():
    id0 = text_chunk_point_id("gdrive:abc123", 0)
    id1 = text_chunk_point_id("gdrive:abc123", 1)
    assert id0 != id1


def test_table_blob_point_id_is_deterministic():
    assert table_blob_point_id("gdrive:abc123:Proveedores") == table_blob_point_id("gdrive:abc123:Proveedores")


def test_text_chunk_and_table_blob_ids_never_collide():
    source_id = "gdrive:abc123:Proveedores"
    assert text_chunk_point_id(source_id, 0) != table_blob_point_id(source_id)
