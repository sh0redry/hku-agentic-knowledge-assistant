from ingestion.web_ingestor import ingest_sources, reindex_markdown_documents


def main() -> int:
    added, failed = ingest_sources(overwrite=True)
    reindex_markdown_documents()
    print(f"HKU data bootstrap complete. Added: {added} | Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
