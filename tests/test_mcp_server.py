import base64

from app.mcp_server import _to_mcp_content, mcp


def _record(**overrides):
    value = {"answer_text": "respuesta", "sources": [], "chart_paths": []}
    value.update(overrides)
    return value


def test_returns_text_with_the_answer():
    assert "respuesta" in _to_mcp_content(_record())[0].text


def test_text_includes_sources_with_name_and_url():
    content = _to_mcp_content(_record(sources=[{"file_name": "x.pdf", "drive_url": "https://example.com/x"}]))
    assert "x.pdf" in content[0].text and "https://example.com/x" in content[0].text


def test_each_chart_becomes_base64_image_content(tmp_path):
    raw = b"\x89PNG\r\n\x1a\n"
    path = tmp_path / "chart.png"
    path.write_bytes(raw)
    image = _to_mcp_content(_record(chart_paths=[str(path)]))[1]
    assert image.mimeType == "image/png"
    assert base64.b64decode(image.data) == raw


def test_missing_chart_file_is_skipped():
    assert len(_to_mcp_content(_record(chart_paths=["missing.png"]))) == 1


def test_no_charts_returns_text_only():
    assert [_item.type for _item in _to_mcp_content(_record())] == ["text"]


def test_tool_is_registered_on_the_server():
    tools = mcp._tool_manager.list_tools()
    tool = next(item for item in tools if item.name == "query_events_kb")
    assert "eventos" in tool.description.lower()
