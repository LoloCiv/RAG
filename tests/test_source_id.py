from app.ingestion.source_id import (
    drive_view_url,
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


def test_drive_view_url_de_pdf_o_doc():
    assert drive_view_url("gdrive:abc123") == "https://drive.google.com/file/d/abc123/view"


def test_drive_view_url_de_tab_de_sheet_apunta_al_archivo_no_al_tab():
    # El link de Drive es al archivo (spreadsheet), no hay URL por-tab --
    # mismo drive_file_id que el source_id de otro tab del mismo archivo.
    assert drive_view_url("gdrive:abc123:Proveedores") == "https://drive.google.com/file/d/abc123/view"
    assert drive_view_url("gdrive:abc123:Presupuesto") == drive_view_url("gdrive:abc123:Proveedores")


def test_drive_view_url_de_source_id_no_reconocido_devuelve_none():
    # Defensivo: la UI no debe romper ni mostrar un link roto si en algun
    # momento aparece un source_id con un formato distinto.
    assert drive_view_url("no-es-un-source-id-valido") is None
    assert drive_view_url("") is None
