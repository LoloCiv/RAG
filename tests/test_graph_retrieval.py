"""format_graph_context: convierte el resultado crudo de Neo4j (anchors +
edges, ya armados como dicts, sin Neo4j vivo) en el bloque de texto
compacto que ve Claude. Funcion pura -- mismo criterio que dedup.py y
cypher.py del sub-proyecto 1."""

from app.graph.retrieval import format_graph_context


def _anchor(name, types, doc_count, norm_name=None):
    return {"name": name, "norm_name": norm_name or name.lower(), "types": types, "doc_count": doc_count}


def _edge(source, rel_type, target, source_ids):
    return {"source": source, "rel_type": rel_type, "target": target, "source_ids": source_ids}


def test_sin_anclas_devuelve_vacio():
    assert format_graph_context([], []) == ""


def test_una_ancla_sin_aristas_se_muestra_igual():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    texto = format_graph_context(anchors, [])
    assert "Catering Buena Mesa" in texto
    assert "Proveedor" in texto
    assert "6" in texto


def test_arista_donde_la_ancla_es_el_origen_se_muestra_con_flecha_saliente():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Catering Buena Mesa", "CONTRATADO_PARA", "Casamiento Perez-Gomez", ["gdrive:abc"])]

    texto = format_graph_context(anchors, edges)

    assert "-CONTRATADO_PARA->" in texto
    assert "Casamiento Perez-Gomez" in texto
    assert "gdrive:abc" in texto


def test_arista_donde_la_ancla_es_el_destino_se_muestra_con_flecha_entrante():
    anchors = [_anchor("Casamiento Perez-Gomez", ["Evento"], 4)]
    edges = [_edge("Catering Buena Mesa", "CONTRATADO_PARA", "Casamiento Perez-Gomez", ["gdrive:abc"])]

    texto = format_graph_context(anchors, edges)

    assert "<-CONTRATADO_PARA-" in texto
    assert "Catering Buena Mesa" in texto


def test_respeta_el_tope_de_anclas():
    anchors = [_anchor(f"Entidad{i}", ["Tipo"], 10 - i) for i in range(10)]
    texto = format_graph_context(anchors, [], max_anchors=3)
    assert texto.count("Entidad") == 3


def test_respeta_el_tope_de_aristas():
    anchors = [_anchor("Hub", ["Tipo"], 20)]
    edges = [_edge("Hub", "REL", f"Nodo{i}", []) for i in range(20)]
    texto = format_graph_context(anchors, edges, max_edges=5)
    assert texto.count("Nodo") == 5


def test_arista_sin_ningun_extremo_ancla_se_ignora():
    # No deberia pasar en la practica (neo4j_client.neighborhood siempre
    # devuelve aristas tocando al menos una ancla), pero si pasa, no debe
    # imprimir basura.
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Entidad X", "REL", "Entidad Y", [])]
    texto = format_graph_context(anchors, edges)
    assert "Entidad X" not in texto
    assert "Entidad Y" not in texto


def test_arista_sin_source_ids_no_rompe():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Catering Buena Mesa", "REL", "Algo", [])]
    texto = format_graph_context(anchors, edges)
    assert "Algo" in texto  # no explota, solo no muestra un source_id


def test_respeta_presupuesto_de_caracteres_cortando_anclas_completas():
    # 5 anclas, cada una con varias aristas -- entran de a una en el tope de
    # anclas/aristas, pero juntas superan un presupuesto de caracteres chico.
    # El corte tiene que dejar afuera anclas ENTERAS, nunca un header sin
    # sus aristas o aristas sin su header.
    anchors = [_anchor(f"Ancla{i}", ["Tipo"], 10 - i) for i in range(5)]
    edges = [_edge(f"Ancla{i}", "REL", f"Nodo{i}", []) for i in range(5)]

    texto = format_graph_context(anchors, edges, max_chars=80)

    # Como maximo entran unas pocas anclas completas en 80 caracteres.
    assert texto.count("Ancla") < 10  # 5 headers + 5 referencias en REL lines seria 10
    # Cualquier ancla que aparezca como header tiene que traer su arista.
    for i in range(5):
        header = f"Ancla{i} [Tipo]"
        edge_line = f"-REL-> Nodo{i}"
        if header in texto:
            assert edge_line in texto, f"Ancla{i} aparece sin su arista"


def test_siempre_muestra_al_menos_la_primera_ancla_aunque_supere_el_presupuesto():
    anchors = [_anchor("Catering Buena Mesa", ["Proveedor"], 6)]
    edges = [_edge("Catering Buena Mesa", "CONTRATADO_PARA", f"Evento{i}", []) for i in range(20)]

    texto = format_graph_context(anchors, edges, max_chars=1)

    assert "Catering Buena Mesa" in texto


def test_arista_entre_dos_anclas_se_imprime_una_sola_vez():
    # Si ambos extremos de la arista son anclas, el recorrido la toca dos
    # veces (una como saliente desde el bloque del ancla-origen, otra como
    # entrante desde el bloque del ancla-destino) -- pero es el mismo hecho
    # visto desde los dos lados y debe imprimirse una sola vez, bajo la
    # primera ancla que la toca en el orden de relevancia ya dado.
    anchors = [
        _anchor("Proveedor A", ["Proveedor"], 10),
        _anchor("Evento B", ["Evento"], 8),
    ]
    edges = [_edge("Proveedor A", "CONTRATADO_PARA", "Evento B", [])]

    texto = format_graph_context(anchors, edges)

    assert texto.count("CONTRATADO_PARA") == 1
    assert "Proveedor A [Proveedor] (10 docs)" in texto
    assert "Evento B [Evento] (8 docs)" in texto
