from app.ingestion.pipeline import build_table_payload, build_text_chunk_payloads
from app.ingestion.sheet_loader import TabData

REQUIRED_TEXT_CHUNK_KEYS = {
    "kind",
    "source_id",
    "drive_file_id",
    "file_name",
    "file_type",
    "chunk_index",
    "text",
    "drive_modified_time",
}

REQUIRED_TABLE_DATA_KEYS = {
    "kind",
    "source_id",
    "drive_file_id",
    "file_name",
    "file_type",
    "sheet_tab",
    "columns",
    "row_count",
    "table_json",
    "truncated",
    "drive_modified_time",
}


def test_text_chunk_payload_has_required_keys_and_discriminator():
    payloads = build_text_chunk_payloads(
        source_id="gdrive:file1",
        drive_file_id="file1",
        file_name="Contrato.pdf",
        file_type="pdf",
        modified_time="2026-01-01T00:00:00Z",
        chunks=["chunk uno", "chunk dos"],
    )
    assert len(payloads) == 2
    for i, payload in enumerate(payloads):
        assert REQUIRED_TEXT_CHUNK_KEYS.issubset(payload.keys())
        assert payload["kind"] == "text_chunk"
        assert payload["chunk_index"] == i


def test_text_chunk_payload_includes_sheet_tab_when_given():
    payloads = build_text_chunk_payloads(
        source_id="gdrive:file1:Proveedores",
        drive_file_id="file1",
        file_name="Proveedores.xlsx",
        file_type="sheet",
        modified_time="2026-01-01T00:00:00Z",
        chunks=["resumen de la planilla"],
        sheet_tab="Proveedores",
    )
    assert payloads[0]["sheet_tab"] == "Proveedores"


def test_table_payload_has_required_keys_and_discriminator():
    tab = TabData(
        tab_name="Proveedores",
        source_id="gdrive:file1:Proveedores",
        text_chunks=["..."],
        columns=["Nombre", "Categoria", "Precio"],
        rows=[{"Nombre": "Acme Catering", "Categoria": "Catering", "Precio": "1200"}],
        row_count=1,
        truncated=False,
    )
    payload = build_table_payload(tab, drive_file_id="file1", file_name="Proveedores.xlsx", modified_time="2026-01-01T00:00:00Z")

    assert REQUIRED_TABLE_DATA_KEYS.issubset(payload.keys())
    assert payload["kind"] == "table_data"
    assert payload["source_id"] == "gdrive:file1:Proveedores"
    assert '"Nombre": "Acme Catering"' in payload["table_json"]
