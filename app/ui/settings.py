"""Diagnóstico explícito para que los servicios externos no frenen el espacio local."""

import logging

import streamlit as st

from app import config

logger = logging.getLogger(__name__)


def render_settings(store=None) -> None:
    st.title("Configuración")
    st.caption("Conexiones y mantenimiento del archivo histórico y las comunicaciones compartidas.")
    with st.container(border=True):
        st.subheader("Acceso y comunicaciones")
        st.write("Acceso corporativo habilitado" if config.AUTH_REQUIRED else "Modo de desarrollo local")
        st.write("Entrada de correo configurada" if config.N8N_WEBHOOK_TOKEN else "Entrada de correo pendiente de configurar")
        from app.collaboration.store import EventStore

        store = store if store is not None else EventStore(config.COLLABORATION_DB_PATH)
        received = store.last_email_received_at()
        st.caption(f"Último correo incorporado (UTC): {received}" if received else "Todavía no se recibieron correos del piloto.")
        st.caption("Los errores del piloto se consultan en n8n → Executions. Reejecutar no duplica correos.")
        st.link_button("Abrir n8n del piloto", "http://localhost:5678")
        if config.ENABLE_OUTBOUND:
            st.warning("La configuración habilita rutas de salida heredadas. Este espacio trabaja en modo lectura; configurá ENABLE_OUTBOUND=false en el servidor.")
        else:
            st.caption("Envíos externos deshabilitados · correo de solo lectura")
    with st.container(border=True):
        st.subheader("Archivo histórico de Drive")
        missing = config.require_env()
        if missing:
            st.warning("Configuración pendiente: " + ", ".join(missing))
        st.caption(f"Carpeta: {config.GOOGLE_DRIVE_FOLDER_ID or 'Sin configurar'}")
        if st.button("Sincronizar archivo histórico", type="primary", disabled=not config.GOOGLE_DRIVE_FOLDER_ID):
            with st.spinner("Sincronizando documentos…"):
                try:
                    from app.ingestion import pipeline

                    result = pipeline.run_resync(config.GOOGLE_DRIVE_FOLDER_ID)
                    st.success(result.summary)
                    for title, details in (("Archivos con errores", result.failed), ("Advertencias", result.warnings)):
                        if details:
                            with st.expander(title):
                                for name, detail in details:
                                    st.text(f"{name}: {detail}")
                except Exception:
                    logger.exception("Falló la sincronización")
                    st.error("No se pudo sincronizar. Revisá la conexión y volvé a intentar con el mismo botón.")
        from app.ingestion import manifest

        files = manifest.load_manifest()
        st.caption(f"{len(files)} archivos registrados")
        if files:
            with st.expander("Documentos sincronizados"):
                st.dataframe([{"Archivo": item["file_name"], "Última ingesta": item["last_ingested_at"]} for item in files.values()], hide_index=True, use_container_width=True)
    with st.container(border=True):
        st.subheader("Estado de los servicios")
        st.caption("Las comprobaciones se ejecutan al solicitarlas. Los eventos permanecen disponibles si el RAG está desconectado.")
        if st.button("Comprobar conexiones"):
            try:
                from qdrant_client import QdrantClient

                client = QdrantClient(url=config.QDRANT_URL, timeout=5)
                try:
                    exists = client.collection_exists(config.QDRANT_COLLECTION)
                    st.success("Búsqueda histórica disponible") if exists else st.warning("La colección histórica todavía no existe. Sincronizá Drive.")
                finally:
                    client.close()
            except Exception:
                logger.exception("Qdrant no disponible")
                st.error("Búsqueda histórica sin conexión. Revisá Qdrant y repetí la comprobación.")
            try:
                from app.graph.neo4j_client import Neo4jGraphStore

                graph = Neo4jGraphStore()
                try:
                    stats = graph.stats()
                    st.success(f"Grafo disponible · {stats['entities']} entidades · {stats['relationships']} relaciones")
                finally:
                    graph.close()
            except Exception:
                logger.exception("Neo4j no disponible")
                st.warning("Grafo sin conexión. La búsqueda puede continuar sin relaciones; revisá Neo4j para recuperarlas.")
