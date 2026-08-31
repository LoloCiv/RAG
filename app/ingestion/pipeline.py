"""Orquestador de la ingesta: listar la carpeta de Drive -> dispatch por
mimeType -> loader especifico -> embeddings -> upsert en Qdrant -> manifest.

Depende de dos modulos que forman parte de la parte de IA/RAG que escribis
vos (ver app/rag/embeddings.py y app/rag/vector_db.py): este archivo asume
que existen

    embeddings.embed_texts(texts: list[str]) -> list[list[float]]

    vector_db.QdrantStorage(url, collection, dim)
        .upsert(ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None
        .delete_by_source_id(source_id: str) -> None

Hasta que esas dos piezas esten implementadas, run_resync() va a fallar con
un NotImplementedError bien explicito (ver los stubs) en vez de un error
críptico.
"""

import json
import logging
from dataclasses import dataclass, field

from app.config import QDRANT_COLLECTION, QDRANT_URL, EMBED_DIM
from app.graph import ingest as graph_ingest
from app.graph.neo4j_client import Neo4jGraphStore
from app.ingestion import drive_client, manifest
from app.ingestion.gdoc_loader import chunk_gdoc_text
from app.ingestion.pdf_loader import load_and_chunk_pdf_bytes, load_pdf_full_text
from app.ingestion.sheet_loader import TabData, load_native_sheet, load_uploaded_xlsx
from app.ingestion.source_id import pdf_or_doc_source_id, table_blob_point_id, text_chunk_point_id
from app.rag import embeddings, vector_db

logger = logging.getLogger(__name__)


@dataclass
class ResyncResult:
    new_or_updated: list[str] = field(default_factory=list)
    skipped_unchanged: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (file_name, error_message)
    # (file_name, warning_message) -- el archivo SE ingirio (no es un
    # "failed"), pero algo amerita revision manual. Hoy solo la usa el PDF
    # sin texto extraible (posible escaneado, Fase 4 del roadmap).
    warnings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"{len(self.new_or_updated)} nuevos/actualizados, "
            f"{len(self.skipped_unchanged)} sin cambios, "
            f"{len(self.failed)} con error, "
            f"{len(self.warnings)} con advertencia"
        )


def get_loader_for_mimetype(mime_type: str) -> str | None:
    """Dispatch puro: mimeType -> categoria de loader. Sin I/O, facil de
    testear con pytest.mark.parametrize sobre los 4 tipos soportados + 1 no
    soportado.
    """
    if mime_type == drive_client.MIMETYPE_PDF:
        return "pdf"
    if mime_type == drive_client.MIMETYPE_GDOC:
        return "gdoc"
    if mime_type in (drive_client.MIMETYPE_GSHEET, drive_client.MIMETYPE_XLSX):
        return "sheet"
    return None


def run_resync(folder_id: str) -> ResyncResult:
    result = ResyncResult()
    man = manifest.load_manifest()
    store = vector_db.QdrantStorage(url=QDRANT_URL, collection=QDRANT_COLLECTION, dim=EMBED_DIM)
    graph_store = Neo4jGraphStore()

    try:
        files = drive_client.list_folder_files(folder_id)
        logger.info("Encontrados %d archivos en la carpeta %s", len(files), folder_id)

        for f in files:
            file_id, name, mime_type, modified_time = f["id"], f["name"], f["mimeType"], f["modifiedTime"]

            # Mismo gate que el camino vectorial: si el archivo no cambio no
            # se re-extrae el grafo tampoco, asi un resync sin cambios no
            # gasta ni una llamada a Claude.
            if not manifest.needs_reingest(man, file_id, modified_time):
                result.skipped_unchanged.append(name)
                continue

            loader_kind = get_loader_for_mimetype(mime_type)
            if loader_kind is None:
                logger.warning("Tipo no soportado, se saltea: %s (%s)", name, mime_type)
                continue

            try:
                old_entry = man.get(file_id)
                source_ids, warning = _ingest_one_file(
                    store, graph_store, file_id, name, mime_type, modified_time, loader_kind, old_entry
                )
                manifest.record_ingested(man, file_id, name, mime_type, modified_time, source_ids)
                result.new_or_updated.append(name)
                if warning:
                    result.warnings.append((name, warning))
            except Exception as e:  # noqa: BLE001 - un archivo con error no debe abortar el resync completo
                logger.exception("Fallo ingiriendo %s", name)
                result.failed.append((name, str(e)))

        manifest.save_manifest(man)
        logger.info("Resync terminado: %s", result.summary)
        return result
    finally:
        graph_store.close()


def _sync_graph_safe(graph_store, source_id: str, document_text: str, file_name: str) -> None:
    """Try/except por documento: un fallo extrayendo o escribiendo el grafo
    NUNCA debe abortar el resync ni el resto de los tabs del mismo archivo.
    El archivo se sigue reportando como ingerido si la parte de Qdrant
    funciono -- el grafo es un paso al lado, no un requisito del vectorial.
    """
    try:
        graph_ingest.sync_document_graph(graph_store, source_id, document_text, file_name)
    except Exception:  # noqa: BLE001 - ver docstring
        logger.exception("Fallo la extraccion/escritura de grafo para %s (%s)", file_name, source_id)


def _ingest_one_file(
    store,
    graph_store,
    file_id: str,
    name: str,
    mime_type: str,
    modified_time: str,
    loader_kind: str,
    old_entry: dict | None,
) -> tuple[list[str], str | None]:
    """Devuelve (source_ids, warning). warning es None salvo un caso hoy:
    un PDF sin texto extraible (posible escaneado, Fase 4 del roadmap --
    PDFReader de LlamaIndex solo lee capa de texto, sin OCR). El archivo
    SE ingiere igual (source_id valido, aunque sin chunks) -- no es un
    error, es una advertencia para revision manual.
    """
    # Si ya existia una version vieja de este archivo, la borramos antes de
    # re-insertar (evita puntos huerfanos si cambio la cantidad de chunks).
    if old_entry:
        for old_source_id in old_entry.get("source_ids", []):
            store.delete_by_source_id(old_source_id)
            # En el grafo no alcanza con borrar: un nodo puede estar
            # compartido con otros documentos, asi que se saca solo el
            # aporte de este source_id y se recolecta lo que quedo huerfano.
            graph_store.remove_source_contribution(old_source_id)

    if loader_kind == "pdf":
        pdf_bytes = drive_client.download_bytes(file_id)
        chunks = load_and_chunk_pdf_bytes(pdf_bytes, name)
        source_id = pdf_or_doc_source_id(file_id)
        _upsert_text_chunks(store, source_id, file_id, name, "pdf", modified_time, chunks)
        _sync_graph_safe(graph_store, source_id, load_pdf_full_text(pdf_bytes, name), name)
        warning = "PDF sin texto extraible (posiblemente escaneado, sin capa OCR)" if not chunks else None
        return [source_id], warning

    if loader_kind == "gdoc":
        text = drive_client.export_text(file_id)
        chunks = chunk_gdoc_text(text, name)
        source_id = pdf_or_doc_source_id(file_id)
        _upsert_text_chunks(store, source_id, file_id, name, "gdoc", modified_time, chunks)
        # El export ya viene como documento entero, no hace falta re-armarlo.
        _sync_graph_safe(graph_store, source_id, text, name)
        return [source_id], None

    if loader_kind == "sheet":
        if mime_type == drive_client.MIMETYPE_GSHEET:
            tabs = load_native_sheet(file_id, name)
        else:
            xlsx_bytes = drive_client.download_bytes(file_id)
            tabs = load_uploaded_xlsx(xlsx_bytes, file_id, name)

        source_ids = []
        for tab in tabs:
            _upsert_text_chunks(store, tab.source_id, file_id, name, "sheet", modified_time, tab.text_chunks, sheet_tab=tab.tab_name)
            _upsert_table_blob(store, tab, file_id, name, modified_time)
            # Un tab es su propia unidad semantica (mismo criterio que el
            # source_id), asi que va como un "documento" al grafo. El texto
            # es la concatenacion de sus chunks: son las filas ya pasadas a
            # oraciones, que es lo que Claude puede leer.
            _sync_graph_safe(
                graph_store,
                tab.source_id,
                "\n".join(tab.text_chunks),
                f"{name} (tab: {tab.tab_name})",
            )
            source_ids.append(tab.source_id)
        return source_ids, None

    raise ValueError(f"loader_kind desconocido: {loader_kind}")  # no deberia pasar, get_loader_for_mimetype ya filtro


def build_text_chunk_payloads(
    source_id: str,
    drive_file_id: str,
    file_name: str,
    file_type: str,
    modified_time: str,
    chunks: list[str],
    sheet_tab: str | None = None,
) -> list[dict]:
    """Funcion pura: arma los payloads de tipo 'text_chunk' (sin tocar
    embeddings ni Qdrant). Separada de _upsert_text_chunks para poder
    testear la FORMA del payload sin credenciales ni servicios corriendo.
    """
    return [
        {
            "kind": "text_chunk",
            "source_id": source_id,
            "drive_file_id": drive_file_id,
            "file_name": file_name,
            "file_type": file_type,
            "chunk_index": i,
            "text": chunk,
            "drive_modified_time": modified_time,
            **({"sheet_tab": sheet_tab} if sheet_tab else {}),
        }
        for i, chunk in enumerate(chunks)
    ]


def build_table_payload(tab: TabData, drive_file_id: str, file_name: str, modified_time: str) -> dict:
    """Funcion pura: arma el payload 'table_data' de un tab (sin tocar
    embeddings ni Qdrant). Ver build_text_chunk_payloads."""
    return {
        "kind": "table_data",
        "source_id": tab.source_id,
        "drive_file_id": drive_file_id,
        "file_name": file_name,
        "file_type": "sheet",
        "sheet_tab": tab.tab_name,
        "columns": tab.columns,
        "row_count": tab.row_count,
        "table_json": json.dumps(tab.rows, ensure_ascii=False),
        "truncated": tab.truncated,
        "drive_modified_time": modified_time,
    }


def _upsert_text_chunks(
    store,
    source_id: str,
    drive_file_id: str,
    file_name: str,
    file_type: str,
    modified_time: str,
    chunks: list[str],
    sheet_tab: str | None = None,
) -> None:
    if not chunks:
        return
    vectors = embeddings.embed_texts(chunks)
    ids = [text_chunk_point_id(source_id, i) for i in range(len(chunks))]
    payloads = build_text_chunk_payloads(source_id, drive_file_id, file_name, file_type, modified_time, chunks, sheet_tab)
    store.upsert(ids, vectors, payloads)


def _upsert_table_blob(store, tab: TabData, drive_file_id: str, file_name: str, modified_time: str) -> None:
    # El blob de tabla tambien necesita un vector (Qdrant exige uno por
    # punto) -- se embebe un resumen corto, no la tabla entera. El path de
    # recuperacion principal es get_by_source_id (scroll con filtro), no
    # similarity search; ver app/agent/tools.py get_source_table.
    summary_text = f"Tabla '{tab.tab_name}' de {file_name}: columnas {', '.join(tab.columns)}, {tab.row_count} filas."
    vector = embeddings.embed_texts([summary_text])[0]
    payload = build_table_payload(tab, drive_file_id, file_name, modified_time)
    store.upsert([table_blob_point_id(tab.source_id)], [vector], [payload])
