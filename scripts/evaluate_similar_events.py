"""Mide registros guardados sin llamar proveedores. --run-live ejecuta los casos reales."""

import argparse
import json
from pathlib import Path
import statistics

from app.similar_events.models import SimilarEventRequest, SimilarEventResult
from app.similar_events.service import validate_citations


def score(case, record):
    result = SimilarEventResult.model_validate(record["similar_events"])
    files = {e.file_name.casefold() for e in result.evidence}
    names = {e.event_name.casefold() for e in result.events}
    expected_files, expected_events = case["expected_files"], case["expected_events"]
    def recall(expected, actual):
        return sum(any(value.casefold() in item for item in actual) for value in expected) / len(expected) if expected else None
    valid, total = 0, 0
    evidence = {e.id: e for e in result.evidence}
    for event in result.events:
        citations = [*event.identity_citations, *event.date_citations, *event.status_citations]
        for field in (event.characteristics, event.similarities, event.differences, event.suppliers, event.costs, event.lessons, event.suggestions):
            citations.extend(c for fact in field for c in fact.citations)
        for citation in citations:
            total += 1
            try:
                validate_citations([citation], evidence)
                valid += 1
            except ValueError:
                pass
    return {"case_id": case["id"], "query_id": record["id"], "retrieved_file_recall": recall(expected_files, files),
            "returned_event_recall": recall(expected_events, names), "expected_empty_correct": not result.events if not expected_files and not expected_events else None,
            "citation_integrity": valid / total if total else None, "elapsed_ms": record.get("elapsed_ms"),
            "usage": record.get("usage", {}), "claim_support_review": "pending_human_review"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/similar_events.json"))
    parser.add_argument("--records", type=Path, required=True, help="Carpeta con <case_id>.json")
    parser.add_argument("--run-live", action="store_true", help="Consume llamadas reales a Claude/Voyage y guarda resultados en --records")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    args.records.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in cases:
        path = args.records / (case["id"] + ".json")
        if args.run_live:
            from app.similar_events.service import find_similar_events
            request = SimilarEventRequest(**{k: v for k, v in case.items() if k in SimilarEventRequest.model_fields})
            record = find_similar_events(request, queries_dir=args.records / "queries")
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if path.exists():
            rows.append(score(case, json.loads(path.read_text(encoding="utf-8"))))
        else:
            rows.append({"case_id": case["id"], "status": "not_run"})
    times = [row["elapsed_ms"] for row in rows if row.get("elapsed_ms") is not None]
    report = {"cases": rows, "median_elapsed_ms": statistics.median(times) if times else None,
              "notes": "Integridad de citas no equivale a respaldo semántico. Revisar cada afirmación contra su fragmento, fechas, homónimos y costos."}
    (args.records / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
