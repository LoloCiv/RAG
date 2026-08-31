"""Arnes de evaluacion de RETRIEVAL: mide si search_knowledge_base
encuentra los documentos correctos para un set fijo de preguntas doradas
(evals/golden_set.json), SIN pasar por Claude -- solo embeddings (Voyage,
tier gratuito de 200M tokens/mes) + Qdrant. Responde "vale la pena invertir
en reranking?" antes de gastar en Claude para el mismo chequeo.

Metricas por pregunta:
- Recall@k: que fraccion de los archivos esperados aparecio en el top-k.
- MRR (mean reciprocal rank): 1/posicion del primer archivo esperado que
  aparecio -- la metrica que un rerank tiene que subir (ver Fase 2 del
  plan). 0 si ninguno aparecio.

Uso:
    python -m scripts.eval_retrieval                  # todo el golden set (con reranking, Fase 2)
    python -m scripts.eval_retrieval --top-k 8         # top_k distinto
    python -m scripts.eval_retrieval --only fernandez_lopez_cronograma_pagos
    python -m scripts.eval_retrieval --no-rerank       # solo busqueda vectorial, para comparar contra el MRR base de la Fase 1 (0.90)

Requiere Qdrant vivo y VOYAGE_API_KEY. NO gasta Claude. Correr dos veces
seguidas sin cambiar el corpus tiene que dar el mismo resultado -- si no,
hay un bug en el arnes o el corpus cambio entre corridas.

Nota de latencia (investigado, no es un bug de este script): medido en la
practica, aprox 1 de cada 3 llamadas a embed_texts() tarda ~50s en vez de
~0.5s -- consistente con reintentos con backoff exponencial del
voyageai.Client (max_retries=8, ver app/rag/embeddings.py) ante fallos
transitorios de red/API, no algo que este script controle. Con el golden
set completo (14 preguntas), una corrida puede tardar entre ~10s y ~10min
segun cuantas llamadas pegan en ese caso. No es que el script se cuelgue.


El juez de calidad de RESPUESTA (compara la respuesta final del agente
contra un hecho esperado, no solo si busco en el lugar correcto) queda
EN STANDBY -- ver score_answer() abajo y la seccion "En standby" del plan
de fases del roadmap de mejoras del RAG.
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import EMBED_DIM, QDRANT_COLLECTION, QDRANT_URL, RERANK_CANDIDATES
from app.ingestion import manifest as manifest_module
from app.rag import embeddings, vector_db

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "evals" / "golden_set.json"
DEFAULT_TOP_K = 5


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_expected_source_ids(expected_files: list[str], manifest: dict) -> list[set[str]]:
    """Para cada nombre de archivo esperado, el set de source_ids que le
    corresponde segun el manifest -- una planilla con varios tabs tiene
    varios source_ids para el MISMO archivo, y cualquiera de ellos cuenta
    como "encontre ese archivo".

    Tira KeyError si un nombre no esta en el manifest: mejor fallar
    ruidoso que medir en silencio contra un golden set desactualizado
    (archivo renombrado, o nunca ingerido).
    """
    by_name = {entry["file_name"]: entry["source_ids"] for entry in manifest.values()}
    result = []
    for file_name in expected_files:
        if file_name not in by_name:
            raise KeyError(
                f"'{file_name}' no esta en el manifest -- el golden set esta "
                f"desactualizado o el archivo no fue ingerido"
            )
        result.append(set(by_name[file_name]))
    return result


def recall_at_k(retrieved_source_ids: list[str], expected_source_id_sets: list[set[str]]) -> float:
    """Fraccion de archivos esperados que aparecieron en algun lugar del
    top-k retornado. 1.0 si todos aparecieron (o si no habia nada que
    encontrar), 0.0 si ninguno."""
    if not expected_source_id_sets:
        return 1.0
    found = sum(
        1
        for expected in expected_source_id_sets
        if any(sid in expected for sid in retrieved_source_ids)
    )
    return found / len(expected_source_id_sets)


def reciprocal_rank(retrieved_source_ids: list[str], expected_source_id_sets: list[set[str]]) -> float:
    """1 / posicion (1-indexada) del primer resultado que pertenece a
    CUALQUIER archivo esperado -- no el primero de la lista de esperados,
    el primero que aparece en el ranking real. 0.0 si ninguno aparecio.

    Depende de que retrieved_source_ids venga en orden real de relevancia
    (ver app/rag/vector_db.py: QdrantStorage.dedup_source_ids, que dedupea
    preservando el orden en el que aparece cada source_id en los resultados
    de Qdrant) -- con un set() esta metrica mediria ruido, no senal.
    """
    if not expected_source_id_sets:
        return 0.0
    all_expected: set[str] = set().union(*expected_source_id_sets)
    for i, sid in enumerate(retrieved_source_ids, start=1):
        if sid in all_expected:
            return 1.0 / i
    return 0.0


def score_answer(question: dict, answer_text: str) -> float:
    """Juez de calidad de RESPUESTA (compara el texto final del agente
    contra un hecho esperado, no solo si el retrieval busco en el lugar
    correcto). EN STANDBY por decision explicita: evaluar Gemini / un
    modelo local / Claude barato antes de gastar en esto -- este arnes
    (Fase 1) mide solo retrieval, que es gratis (nada de Claude).

    Ver la seccion "En standby" del plan de fases del roadmap de mejoras
    del RAG.
    """
    raise NotImplementedError(
        "El juez de calidad de respuesta esta en standby -- ver 'En standby' "
        "en el plan de fases del roadmap de mejoras del RAG."
    )


def format_report(results: list[dict]) -> str:
    """Tabla por pregunta + promedio (Recall@k / MRR). Funcion pura --
    mismo criterio que format_comparison en scripts/benchmark_agent.py."""
    lines = [f"{'pregunta':40s} {'recall':>8s} {'rr':>8s}"]
    for r in results:
        lines.append(f"{r['id']:40s} {r['recall']:>8.2f} {r['rr']:>8.2f}")

    if results:
        avg_recall = sum(r["recall"] for r in results) / len(results)
        avg_rr = sum(r["rr"] for r in results) / len(results)  # promedio de rr == MRR
    else:
        avg_recall = avg_rr = 0.0

    lines.append("-" * 58)
    lines.append(f"{'PROMEDIO (Recall@k / MRR)':40s} {avg_recall:>8.2f} {avg_rr:>8.2f}")
    return "\n".join(lines)


def evaluate_question(
    question: dict, manifest: dict, store: vector_db.QdrantStorage, top_k: int, rerank: bool = True
) -> dict:
    """Corre UNA pregunta del golden set contra Qdrant real (embedding de
    la pregunta + busqueda), sin Claude. Depende de servicios vivos -- no
    se testea con pytest (mismo criterio que run_question en
    scripts/benchmark_agent.py).

    rerank=True (default) sigue EXACTAMENTE el mismo camino que
    search_knowledge_base (app/agent/tools.py): pide RERANK_CANDIDATES
    candidatos y los reordena con QdrantStorage.rerank_results() antes de
    medir. rerank=False mide la busqueda vectorial sola (--no-rerank en la
    CLI) -- sirve para reproducir el numero base de la Fase 1 (MRR=0.90) y
    comparar antes/vs/despues sin tener que volver a un commit viejo.
    """
    expected = resolve_expected_source_ids(question["expected_files"], manifest)
    query_vector = embeddings.embed_texts([question["question"]], input_type="query")[0]
    candidate_k = max(top_k, RERANK_CANDIDATES) if rerank else top_k
    chunks = store.search(query_vector, top_k=candidate_k, kind_filter="text_chunk")
    if rerank:
        chunks = vector_db.QdrantStorage.rerank_results(question["question"], chunks, top_k)
    # Lista correlacionada por chunk desde la Fase 2 -- dedupear a
    # "sources" a nivel documento, igual que search_knowledge_base.
    retrieved = vector_db.QdrantStorage.dedup_source_ids(chunks)
    return {
        "id": question["id"],
        "recall": recall_at_k(retrieved, expected),
        "rr": reciprocal_rank(retrieved, expected),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help=f"default {DEFAULT_TOP_K}")
    parser.add_argument("--only", type=str, default=None, help="id de una sola pregunta del golden set")
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="medir solo la busqueda vectorial (sin reranking) -- para comparar contra el numero base de la Fase 1",
    )
    args = parser.parse_args()

    golden_set = load_golden_set()
    if args.only:
        golden_set = [q for q in golden_set if q["id"] == args.only]
        if not golden_set:
            print(f"No hay ninguna pregunta con id={args.only!r}")
            sys.exit(1)

    manifest = manifest_module.load_manifest()
    store = vector_db.QdrantStorage(url=QDRANT_URL, collection=QDRANT_COLLECTION, dim=EMBED_DIM)

    # Progreso por pregunta (no solo el reporte final): la latencia de
    # embed_texts() es intermitente en la practica (ver nota en el
    # docstring del modulo, ~1 de cada 3 llamadas tarda ~50s en vez de
    # ~0.5s por reintentos del SDK de Voyage) -- sin esto, una corrida
    # lenta se ve identica a una colgada.
    results = []
    for i, q in enumerate(golden_set, start=1):
        print(f"[{i}/{len(golden_set)}] {q['id']}...", end=" ", flush=True)
        r = evaluate_question(q, manifest, store, args.top_k, rerank=not args.no_rerank)
        print(f"recall={r['recall']:.2f} rr={r['rr']:.2f}", flush=True)
        results.append(r)

    print()
    print(format_report(results))


if __name__ == "__main__":
    main()
