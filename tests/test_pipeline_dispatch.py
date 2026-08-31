import pytest

from app.ingestion import drive_client
from app.ingestion.pipeline import get_loader_for_mimetype


@pytest.mark.parametrize(
    "mime_type,expected",
    [
        (drive_client.MIMETYPE_PDF, "pdf"),
        (drive_client.MIMETYPE_GDOC, "gdoc"),
        (drive_client.MIMETYPE_GSHEET, "sheet"),
        (drive_client.MIMETYPE_XLSX, "sheet"),
        ("image/png", None),  # tipo no soportado -> se saltea, no explota
    ],
)
def test_get_loader_for_mimetype(mime_type, expected):
    assert get_loader_for_mimetype(mime_type) == expected
