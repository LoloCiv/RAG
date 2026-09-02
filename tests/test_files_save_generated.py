"""save_generated_files: baja los archivos que Claude genera con la tool
de code_execution (charts) via la Files API. Antes solo reconocia
bash_code_execution_tool_result (el sub-tool de comandos de shell) --
pero CODE_EXECUTION_TOOL esta declarada como code_execution_20260120
(programmatic tool calling, de la que depende get_source_table), y
cuando Claude usa el sub-tool DIRECTO code_execution (celda de Python,
sin pasar por bash), el tipo real del bloque de resultado no lleva el
prefijo "bash_": code_execution_tool_result / code_execution_result /
code_execution_output -- mismo shape que la variante bash-prefijada
(confirmado comparando los tipos del SDK), pero un string de tipo
distinto que el chequeo viejo nunca matcheaba. Bug real: un grafico que
Claude genero exitosamente nunca se adjuntaba en la UI.

Usa fakes con atributos (no dicts) -- getattr(block, "type", None) es
como el codigo real accede al tipo, igual que los objetos del SDK."""

from types import SimpleNamespace

from app.agent.files import save_generated_files


class _FakeFilesAPI:
    def __init__(self, filename: str, content: bytes):
        self._filename = filename
        self._content = content
        self.downloaded_file_ids: list[str] = []

    def retrieve_metadata(self, file_id: str):
        return SimpleNamespace(filename=self._filename)

    def download(self, file_id: str):
        self.downloaded_file_ids.append(file_id)
        return SimpleNamespace(write_to_file=lambda path: None)


class _FakeBeta:
    def __init__(self, files_api: _FakeFilesAPI):
        self.files = files_api


class _FakeClient:
    def __init__(self, files_api: _FakeFilesAPI):
        self.beta = _FakeBeta(files_api)


def _output_block(file_id: str, bash_prefix: bool) -> SimpleNamespace:
    type_name = "bash_code_execution_output" if bash_prefix else "code_execution_output"
    return SimpleNamespace(type=type_name, file_id=file_id)


def _result_block(file_id: str, bash_prefix: bool) -> SimpleNamespace:
    tool_result_type = "bash_code_execution_tool_result" if bash_prefix else "code_execution_tool_result"
    result_type = "bash_code_execution_result" if bash_prefix else "code_execution_result"
    return SimpleNamespace(
        type=tool_result_type,
        content=SimpleNamespace(
            type=result_type,
            content=[_output_block(file_id, bash_prefix)],
        ),
    )


def test_extrae_archivo_de_bloque_code_execution_tool_result_sin_prefijo_bash(monkeypatch, tmp_path):
    # El caso real que rompia: code_execution_20260120 (programmatic tool
    # calling) via el sub-tool directo, sin "bash_".
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="grafico.png", content=b"fake-png")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_abc", bash_prefix=False)]

    saved = save_generated_files(client, blocks)

    assert saved == [str(tmp_path / "grafico.png")]
    assert files_api.downloaded_file_ids == ["file_abc"]


def test_sigue_funcionando_con_bash_code_execution_tool_result(monkeypatch, tmp_path):
    # No regresionar el sub-tool bash_code_execution (comandos de shell).
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="reporte.pdf", content=b"fake-pdf")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_xyz", bash_prefix=True)]

    saved = save_generated_files(client, blocks)

    assert saved == [str(tmp_path / "reporte.pdf")]


def test_bloque_que_no_es_resultado_de_code_execution_se_ignora(tmp_path):
    blocks = [SimpleNamespace(type="text", text="hola")]

    assert save_generated_files(_FakeClient(_FakeFilesAPI("x", b"")), blocks) == []


def test_resultado_de_error_no_intenta_bajar_nada(tmp_path):
    error_block = SimpleNamespace(
        type="code_execution_tool_result",
        content=SimpleNamespace(type="code_execution_tool_result_error", error_code="timeout"),
    )

    assert save_generated_files(_FakeClient(_FakeFilesAPI("x", b"")), [error_block]) == []


def test_nombre_de_archivo_con_path_traversal_se_saltea(monkeypatch, tmp_path):
    # OJO: os.path.basename("../../etc/passwd") == "passwd" (un nombre
    # valido) -- NO dispara el guard. El guard existente solo cubre el
    # caso donde el basename resultante es exactamente "." o ".." (ej.
    # un filename que termina en "/.." tal cual), asi que el test tiene
    # que usar ESE caso, no una ruta con basename valido al final.
    import app.agent.files as files_module

    monkeypatch.setattr(files_module, "CHART_OUTPUTS_DIR", tmp_path)
    files_api = _FakeFilesAPI(filename="../..", content=b"x")
    client = _FakeClient(files_api)
    blocks = [_result_block("file_evil", bash_prefix=False)]

    assert save_generated_files(client, blocks) == []
