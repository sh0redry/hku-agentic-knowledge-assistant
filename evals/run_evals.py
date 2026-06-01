import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from dotenv import load_dotenv
load_dotenv(PROJECT / ".env")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import config
from db.vector_db_manager import VectorDbManager
from core.chat_interface import ChatInterface
from core.rag_system import RAGSystem


DEFAULT_QUESTIONS = ROOT / "evals" / "questions.jsonl"
DEFAULT_OUTPUT = ROOT / "evals" / "results.jsonl"


def load_questions(path: Path) -> list[dict]:
    questions = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            questions.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return questions


def source_hit(doc_metadata: dict, expected_source_ids: list[str]) -> bool:
    source_id = doc_metadata.get("source_id", "")
    source = doc_metadata.get("source", "")
    source_url = doc_metadata.get("source_url", "")
    haystack = " ".join([source_id, source, source_url]).lower()
    return any(expected.lower() in haystack for expected in expected_source_ids)


def retrieved_record(doc) -> dict:
    metadata = doc.metadata or {}
    return {
        "source_id": metadata.get("source_id"),
        "source": metadata.get("source"),
        "source_url": metadata.get("source_url"),
        "title": metadata.get("title"),
        "category": metadata.get("category"),
        "parent_id": metadata.get("parent_id"),
        "preview": doc.page_content[:300],
    }


def evaluate_retrieval(questions: list[dict], k: int, threshold: float) -> tuple[list[dict], dict]:
    vector_db = VectorDbManager()
    vector_db.create_collection(config.CHILD_COLLECTION)
    collection = vector_db.get_collection(config.CHILD_COLLECTION)

    results = []
    for item in questions:
        docs = collection.similarity_search(item["question"], k=k, score_threshold=threshold)
        expected = item.get("expected_source_ids", [])
        hit = bool(docs) if not expected else any(
            source_hit(doc.metadata or {}, expected) for doc in docs
        )
        citation_ready = any((doc.metadata or {}).get("source_url") for doc in docs)
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "language": item.get("language"),
                "category": item.get("category"),
                "expected_source_ids": expected,
                "retrieval_hit": hit,
                "citation_ready": citation_ready,
                "retrieved_count": len(docs),
                "retrieved": [retrieved_record(doc) for doc in docs],
            }
        )

    summary = summarize(results)
    return results, summary


def evaluate_answers(questions: list[dict], retrieval_results: list[dict]) -> list[dict]:
    rag_system = RAGSystem()
    rag_system.initialize()
    chat = ChatInterface(rag_system)

    by_id = {result["id"]: result for result in retrieval_results}
    answer_results = []
    for item in questions:
        rag_system.reset_thread()
        final_chunk = None
        for chunk in chat.chat(item["question"], []):
            final_chunk = chunk

        if isinstance(final_chunk, list):
            answer = "\n".join(msg.get("content", "") for msg in final_chunk if msg.get("content")).strip()
        else:
            answer = str(final_chunk or "")

        base = by_id[item["id"]]
        expected_terms = item.get("must_include", [])
        answer_lower = answer.lower()
        term_hits = [term for term in expected_terms if term.lower() in answer_lower]
        answer_results.append(
            {
                **base,
                "answer": answer,
                "answer_has_source_section": "sources" in answer_lower or "来源" in answer,
                "must_include_hits": term_hits,
                "must_include_total": len(expected_terms),
            }
        )
    return answer_results


def summarize(results: list[dict]) -> dict:
    total = len(results)
    hits = sum(1 for result in results if result["retrieval_hit"])
    citation_ready = sum(1 for result in results if result["citation_ready"])
    by_category = defaultdict(lambda: {"total": 0, "hits": 0})
    by_language = defaultdict(lambda: {"total": 0, "hits": 0})

    for result in results:
        for bucket, key in ((by_category, result.get("category")), (by_language, result.get("language"))):
            bucket[key]["total"] += 1
            bucket[key]["hits"] += int(result["retrieval_hit"])

    def rates(bucket):
        return {
            key: {
                **value,
                "hit_rate": round(value["hits"] / value["total"], 3) if value["total"] else 0,
            }
            for key, value in sorted(bucket.items())
        }

    return {
        "total": total,
        "retrieval_hits": hits,
        "retrieval_hit_rate": round(hits / total, 3) if total else 0,
        "citation_ready": citation_ready,
        "citation_ready_rate": round(citation_ready / total, 3) if total else 0,
        "by_category": rates(by_category),
        "by_language": rates(by_language),
        "failed_ids": [result["id"] for result in results if not result["retrieval_hit"]],
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run HKU RAG retrieval and optional answer evals.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--k", type=int, default=config.DIRECT_RETRIEVAL_LIMIT)
    parser.add_argument("--threshold", type=float, default=config.SEARCH_SCORE_THRESHOLD)
    parser.add_argument("--answers", action="store_true", help="Also run full answer generation. This can consume LLM quota.")
    args = parser.parse_args(argv)

    questions = load_questions(args.questions)
    retrieval_results, summary = evaluate_retrieval(questions, args.k, args.threshold)

    records = evaluate_answers(questions, retrieval_results) if args.answers else retrieval_results
    write_jsonl(args.output, records)

    category_counts = Counter(item.get("category") for item in questions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Questions by category: {dict(category_counts)}")
    print(f"Wrote results: {args.output}")
    return 1 if summary["failed_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
