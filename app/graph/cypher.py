"""Sanitizacion de labels y tipos de relacion para interpolar en Cypher.

Cypher no permite parametrizar labels (`:Proveedor`) ni tipos de relacion
(`[:CONTRATADO_PARA]`) -- van si o si interpolados en el string de la query.
Como el `type`/`relation_type` de cada entidad lo elige Claude libremente a
partir del contenido del documento, ese texto es entrada no confiable y hay
que reducirlo a un identificador seguro ANTES de que toque una query.

El enfoque es whitelist, no escapado: en vez de intentar escapar backticks
(un juego que se pierde), se deja pasar unicamente \\w y se convierte todo
lo demas a "_". Un resultado que solo contiene letras/digitos/guion_bajo no
puede cerrar un backtick ni abrir un parentesis, asi que no hay superficie de
inyeccion aunque el documento fuente sea hostil.
"""

import re

from app.graph.dedup import strip_accents

# Cuanto mas largo que esto, es basura o un intento de abuso -- ningun tipo
# de entidad razonable necesita 100+ caracteres.
_MAX_LEN = 100


def sanitize_label(raw: str, default: str = "Entity") -> str:
    """`type` libre de Claude -> label seguro para Cypher.

    Ademas de la whitelist, el resultado es CANONICO: sin tildes y con un
    case fijo. Claude escribe el mismo tipo distinto segun el documento
    ("Proveedor de Catering", "proveedor de catering", "Locación"), y sin
    esto Neo4j terminaria con varios labels paralelos para lo mismo -- lo
    que rompe cualquier consulta por tipo mas adelante.
    """
    cleaned = re.sub(r"[^\w]", "_", strip_accents(raw).strip(), flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return default
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    # Minusculas + inicial en mayuscula: determinístico venga como venga, y
    # se lee natural en español (donde no se capitaliza cada palabra), a
    # diferencia de un PascalCase por segmento.
    cleaned = cleaned.lower()
    return (cleaned[0].upper() + cleaned[1:])[:_MAX_LEN]


def sanitize_rel_type(raw: str, default: str = "RELACIONADO_CON") -> str:
    """`relation_type` libre de Claude -> tipo de relacion seguro.

    Misma whitelist que sanitize_label, en mayusculas por convencion de
    Cypher para tipos de relacion.
    """
    return sanitize_label(raw, default=default).upper()
