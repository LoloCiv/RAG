"""Modelos Pydantic tipados, adaptados de custom_types.py del repo de
referencia. Estos ya estan completos -- no forman parte de lo que tenes que
escribir vos, son solo el "contrato" de datos que usan embeddings.py y
vector_db.py.
"""

import pydantic


class SearchResult(pydantic.BaseModel):
    """Resultado de QdrantStorage.search() -- ver vector_db.py."""

    contexts: list[str]
    sources: list[str]


class TableBlob(pydantic.BaseModel):
    """Resultado de QdrantStorage.get_by_source_id() -- payload de un punto
    'table_data' (ver pipeline.py:_upsert_table_blob para como se arma)."""

    source_id: str
    file_name: str
    sheet_tab: str
    columns: list[str]
    row_count: int
    table_json: str
    truncated: bool
