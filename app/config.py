"""Configuracion centralizada: variables de entorno + constantes del proyecto.

Todo lo que otros modulos necesiten leer de .env o que sea una constante
"de diseno" (dimension de embeddings, tamano de chunk, etc.) vive aca, para
no tener os.getenv(...) desperdigados por el codigo.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths del proyecto ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
CHART_OUTPUTS_DIR = DATA_DIR / "chart_outputs"
GOOGLE_CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
GOOGLE_TOKEN_PATH = PROJECT_ROOT / "token.json"

for _dir in (DOWNLOADS_DIR, DATA_DIR, CHART_OUTPUTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# --- API keys / conexiones ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "events_kb")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

# --- Grafo de conocimiento (Neo4j) ---
# Bolt es el protocolo binario que usa el driver Python; el browser de Neo4j
# escucha aparte en el 7474 (ver README).
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Umbral (0-100) de similitud difusa para considerar que dos nombres de
# entidad son la misma cosa. 90 tolera reordenamientos/typos/puntuacion
# ("Buena Mesa Catering" == "Catering Buena Mesa") pero rechaza entidades
# genuinamente distintas ("Catering Mala Mesa"). Ver app/graph/dedup.py.
GRAPH_DEDUP_THRESHOLD = int(os.getenv("GRAPH_DEDUP_THRESHOLD", "90"))

# --- Enriquecimiento del agente con el grafo (sub-proyecto 2) ---
# Cuantas entidades "ancla" (las que aparecen en los documentos que ya
# encontro la busqueda semantica) se muestran en el mapa que ve Claude.
# 5: alcanza para orientar sin inflar el prompt.
GRAPH_MAX_ANCHORS = int(os.getenv("GRAPH_MAX_ANCHORS", "5"))
# Techo de aristas totales en el mapa. 40 cubre con margen las 11 aristas
# del nodo mas conectado del corpus de prueba ("Catering Buena Mesa") y
# mantiene el bloque en el orden de los 200-400 tokens que justifica esta
# palanca (contra los ~4.000 que cuesta una busqueda de chunks).
GRAPH_MAX_EDGES = int(os.getenv("GRAPH_MAX_EDGES", "40"))
# Techo de TAMANO real del bloque de mapa, en caracteres. GRAPH_MAX_ANCHORS/
# GRAPH_MAX_EDGES cuentan elementos, no tokens, y por eso no escalan: 11
# aristas de una sola ancla entran comodas en el presupuesto de 200-400
# tokens del spec, pero una pregunta amplia que resuelve 5 anclas
# simultaneas -- cada una con sus propias aristas -- se va a ~970 tokens
# aunque respete los mismos topes de cantidad (medido contra el corpus
# real). Este es el tope que de verdad gobierna el tamano del texto:
# format_graph_context corta anclas ENTERAS (nunca a la mitad) apenas se
# excede. 1600 ~= 400 tokens a razon de ~4 chars/token -- una regla de dedo
# a proposito, no vale la pena una llamada de tokenizer por busqueda.
GRAPH_MAX_CHARS = int(os.getenv("GRAPH_MAX_CHARS", "1600"))

# --- Modelos ---
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
# voyage-4-lite (no voyage-large-2): los modelos "voyage-4*" tienen 200M
# tokens gratis por mes -- voyage-large-2 es un modelo legacy que Voyage
# excluyo explicitamente de esa franquicia gratuita, asi que para un POC
# conviene el modelo nuevo. Dimension real confirmada con una llamada real:
# 1024 (default de voyage-4-lite; tambien soporta 256/512/2048 via
# output_dimension si en algun momento hiciera falta).
EMBED_MODEL = "voyage-4-lite"
EMBED_DIM = 1024

# --- Chunking (mismo criterio que el repo de referencia) ---
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# --- Google API scopes ---
# Solo lectura: este POC nunca escribe en el Drive del usuario.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

# --- Limite de filas por tabla ingerida (ver sheet_loader.py) ---
MAX_TABLE_ROWS = 2000


def require_env() -> list[str]:
    """Devuelve la lista de variables de entorno obligatorias que faltan.

    Util para que el arranque de la app (Streamlit) falle con un mensaje
    claro en vez de un traceback crudo mas adelante.
    """
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not VOYAGE_API_KEY:
        missing.append("VOYAGE_API_KEY")
    if not GOOGLE_DRIVE_FOLDER_ID:
        missing.append("GOOGLE_DRIVE_FOLDER_ID")
    if not NEO4J_PASSWORD:
        missing.append("NEO4J_PASSWORD")
    return missing
