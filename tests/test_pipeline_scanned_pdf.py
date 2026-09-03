"""Deteccion de PDFs escaneados (Fase 4 -- robustez): pdf_loader.py usa el
PDFReader de LlamaIndex, que solo extrae capa de texto. Un PDF escaneado
(sin OCR) entra con 0 chunks y, sin este chequeo, se registraba como
ingerido exitosamente sin que nadie se enterara de que no aporto nada a
la base de conocimiento.

_ingest_one_file() ahora devuelve (source_ids, warning | None); run_resync()
junta esos warnings en ResyncResult.warnings, separado de failed (no es un
error -- el archivo SI se ingirio, solo que no tenia texto extraible)."""

from app.ingestion.pipeline import ResyncResult, _ingest_one_file
import app.ingestion.pipeline as pipeline_module


class _FakeStore:
    def upsert(self, ids, vectors, payloads):
        pass


class _FakeGraphStore:
    pass


def _patch_pdf_loaders(monkeypatch, chunks: list[str]):
    monkeypatch.setattr(pipeline_module.drive_client, "download_bytes", lambda file_id: b"fake-pdf-bytes")
    monkeypatch.setattr(pipeline_module, "load_and_chunk_pdf_bytes", lambda pdf_bytes, name: chunks)
    monkeypatch.setattr(pipeline_module, "load_pdf_full_text", lambda pdf_bytes, name: "\n".join(chunks))
    monkeypatch.setattr(pipeline_module.graph_ingest, "sync_document_graph", lambda *a, **k: None)
    # El test valida el warning del loader, no Voyage; una llamada real vuelve
    # la suite dependiente de red y consume credito sin probar nada adicional.
    monkeypatch.setattr(pipeline_module.embeddings, "embed_texts", lambda texts: [[0.0] for _ in texts])


def test_pdf_sin_chunks_devuelve_warning(monkeypatch):
    _patch_pdf_loaders(monkeypatch, chunks=[])

    source_ids, warning = _ingest_one_file(
        _FakeStore(), _FakeGraphStore(), "file123", "escaneado.pdf", "application/pdf", "2026-01-01", "pdf", None
    )

    assert source_ids == ["gdrive:file123"]  # se ingiere igual (source_id existe, aunque sin chunks)
    assert warning is not None
    assert "escaneado" in warning.lower() or "texto" in warning.lower()


def test_pdf_con_chunks_no_devuelve_warning(monkeypatch):
    _patch_pdf_loaders(monkeypatch, chunks=["un chunk con texto real"])

    source_ids, warning = _ingest_one_file(
        _FakeStore(), _FakeGraphStore(), "file456", "normal.pdf", "application/pdf", "2026-01-01", "pdf", None
    )

    assert source_ids == ["gdrive:file456"]
    assert warning is None


def test_gdoc_y_sheet_no_devuelven_warning_aunque_esten_vacios(monkeypatch):
    # El chequeo es especifico de PDF (unico loader con el problema descrito
    # en el plan) -- gdoc/sheet no deben generar falsos positivos.
    monkeypatch.setattr(pipeline_module.drive_client, "export_text", lambda file_id: "")
    monkeypatch.setattr(pipeline_module, "chunk_gdoc_text", lambda text, name: [])
    monkeypatch.setattr(pipeline_module.graph_ingest, "sync_document_graph", lambda *a, **k: None)

    source_ids, warning = _ingest_one_file(
        _FakeStore(), _FakeGraphStore(), "file789", "vacio.gdoc", "application/vnd.google-apps.document", "2026-01-01", "gdoc", None
    )

    assert warning is None


def test_resync_result_summary_incluye_cantidad_de_warnings():
    # Mismo patron que "X con error" -- siempre visible, incluso en 0, para
    # que el conteo sea consistente entre corridas (no aparece/desaparece).
    con_warning = ResyncResult(
        new_or_updated=["a.pdf", "b.pdf"],
        warnings=[("b.pdf", "PDF sin texto extraible (posiblemente escaneado)")],
    )
    assert "1 con advertencia" in con_warning.summary

    sin_warning = ResyncResult(new_or_updated=["a.pdf"])
    assert "0 con advertencia" in sin_warning.summary
