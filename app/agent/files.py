"""Helper para bajar los archivos que genera la tool de ejecucion de codigo
(charts) via la Files API de Anthropic. Esto es mecanica de API, no una
decision de diseno de IA -- ya viene resuelto, no forma parte de lo que
tenes que escribir vos.

Uso tipico desde claude_agent.py, con los bloques de assistant de los
mensajes nuevos del turno (ver _build_result en claude_agent.py):

    chart_paths = save_generated_files(client, assistant_blocks)
"""

import logging
import os

from app.config import CHART_OUTPUTS_DIR

logger = logging.getLogger(__name__)

# CODE_EXECUTION_TOOL (app/agent/tools.py) es code_execution_20260120,
# necesaria para programmatic tool calling (de la que depende
# get_source_table). Claude puede generar archivos por dos sub-tools
# distintos segun el caso -- bash_code_execution (comandos de shell) o
# el sub-tool directo code_execution (celda de Python, sin pasar por
# bash) -- y cada uno usa un nombre de tipo de bloque distinto para lo
# que es, por lo demas, exactamente el mismo shape (confirmado
# comparando venv/Lib/site-packages/anthropic/types/beta/
# beta_code_execution_output_block.py vs
# beta_bash_code_execution_output_block.py: mismo campo file_id, type
# literal distinto). Sin este mapeo, un archivo generado por el segundo
# sub-tool nunca se reconocia -- bug real, un grafico generado con exito
# nunca se adjuntaba en la UI.
_CODE_EXECUTION_RESULT_TYPES = {
    "bash_code_execution_tool_result": ("bash_code_execution_result", "bash_code_execution_output"),
    "code_execution_tool_result": ("code_execution_result", "code_execution_output"),
}


def save_generated_files(client, content_blocks: list) -> list[str]:
    """Recorre los bloques de una respuesta de Claude buscando archivos
    generados por la tool de codigo (charts), los baja via la Files API y
    los guarda en data/chart_outputs/. Devuelve la lista de paths locales.
    """
    saved_paths: list[str] = []

    for block in content_blocks:
        result_type_names = _CODE_EXECUTION_RESULT_TYPES.get(getattr(block, "type", None))
        if result_type_names is None:
            continue
        expected_result_type, expected_output_type = result_type_names

        result = block.content
        if getattr(result, "type", None) != expected_result_type:
            # Es un error de la tool (result.error_code), no archivos.
            logger.warning("code_execution devolvio un error: %r", result)
            continue

        for file_ref in result.content or []:
            if getattr(file_ref, "type", None) != expected_output_type:
                continue

            try:
                metadata = client.beta.files.retrieve_metadata(file_ref.file_id)
                file_content = client.beta.files.download(file_ref.file_id)

                # Sanitizar el nombre: evita path traversal si Claude (o un
                # nombre de archivo raro) devolviera algo como "../../etc".
                safe_name = os.path.basename(metadata.filename)
                if not safe_name or safe_name in (".", ".."):
                    logger.warning("Nombre de archivo invalido, se saltea: %r", metadata.filename)
                    continue

                output_path = str(CHART_OUTPUTS_DIR / safe_name)
                file_content.write_to_file(output_path)
                saved_paths.append(output_path)
                logger.info("Grafico guardado en %s", output_path)
            except Exception:
                logger.exception("Fallo bajando el archivo generado %s", file_ref.file_id)

    return saved_paths
