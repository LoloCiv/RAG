# Evaluación de retrieval y reranking (Fases 1-2)

Antes de gastar en mejorar el retrieval hacía falta poder medirlo. El arnés
(`scripts/eval_retrieval.py`) corre un golden set fijo de 14 preguntas
(`evals/golden_set.json`, mezcla de hechos de archivo único y multi-archivo
sobre `sample_data/`) contra Qdrant + Voyage reales — **sin gastar Claude**:

```bash
python -m scripts.eval_retrieval                  # todo el golden set, con reranking
python -m scripts.eval_retrieval --no-rerank       # solo búsqueda vectorial, para comparar
python -m scripts.eval_retrieval --only fernandez_lopez_cronograma_pagos
```

Métricas por pregunta: **Recall@k** (¿aparecieron los archivos esperados en
el top-k?) y **MRR** (qué tan arriba salió el primero correcto — la que
mueve el reranking).

| | Recall@k | MRR |
|---|---|---|
| Sin reranking (base, Fase 1) | 1.00 | 0.90 |
| Con reranking (Fase 2) | 1.00 | **1.00** |

El reranking (`QdrantStorage.rerank_results()` en `app/rag/vector_db.py`,
modelo `rerank-2.5-lite` de Voyage — tier gratuito, igual que los
embeddings) trae `RERANK_CANDIDATES` candidatos de más antes de recortar a
`top_k`, y degrada con gracia al orden vectorial original si Voyage falla
(cuota, red) sin romper la búsqueda.

