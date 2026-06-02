import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import config
from retrieval.bilingual import aliases_for_source, aliases_markdown
from utils import pdf_to_markdown


FRONT_MATTER_BOUNDARY = "---"


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip(), flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "document"


def front_matter(metadata: dict) -> str:
    return (
        f"{FRONT_MATTER_BOUNDARY}\n"
        f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n"
        f"{FRONT_MATTER_BOUNDARY}\n\n"
    )


def source_metadata(source: dict, title: str | None = None) -> dict:
    resolved_title = title or source.get("title") or source.get("name") or source["id"]
    aliases = aliases_for_source(source.get("id"), source.get("category"), resolved_title)
    return {
        "source_id": source["id"],
        "source_url": source["url"],
        "title": resolved_title,
        "category": source.get("category", ""),
        "audience": source.get("audience", ""),
        "degree_level": source.get("degree_level", ""),
        "source_type": source.get("source_type", "web"),
        "official": bool(source.get("official", False)),
        "aliases": aliases,
        "last_indexed_at": datetime.now(timezone.utc).isoformat(),
    }


def split_front_matter(markdown: str) -> tuple[dict, str]:
    text = markdown.lstrip()
    if not text.startswith(FRONT_MATTER_BOUNDARY):
        return {}, markdown

    parts = text.split(FRONT_MATTER_BOUNDARY, 2)
    if len(parts) < 3:
        return {}, markdown

    raw_metadata = parts[1].strip()
    body = parts[2].lstrip()
    try:
        return json.loads(raw_metadata), body
    except json.JSONDecodeError:
        return {}, markdown


class HTMLToMarkdownParser(HTMLParser):
    BLOCK_TAGS = {"article", "main", "section", "div", "p", "tr", "table", "ul", "ol"}
    SKIP_TAGS = {"script", "style", "svg", "noscript", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.current_link: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.parts.append("\n\n" + ("#" * level) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            href = attrs.get("href")
            self.current_link = href.strip() if href else None
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        if tag == "a":
            self.current_link = None
        elif tag in self.BLOCK_TAGS or tag in {"h1", "h2", "h3", "h4", "h5", "h6", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if not text:
            return
        if self.current_link and self.current_link.startswith(("http://", "https://")):
            self.parts.append(f"[{text}]({self.current_link})")
        else:
            self.parts.append(text)
        self.parts.append(" ")

    def markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_title(html_text: str, fallback: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback
    title = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
    return title or fallback


def fetch_html(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "HKU-Agentic-Knowledge-Assistant/0.1 (+https://github.com/)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def download_binary(url: str, output_path: Path, timeout: int = 60) -> None:
    request = Request(
        url,
        headers={
            "User-Agent": "HKU-Agentic-Knowledge-Assistant/0.1 (+https://github.com/)",
            "Accept": "application/pdf,*/*",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        output_path.write_bytes(response.read())


def source_to_markdown(source: dict, html_text: str) -> str:
    title = source.get("title") or source.get("name") or extract_title(html_text, source["id"])
    parser = HTMLToMarkdownParser()
    parser.feed(html_text)
    parser.close()

    metadata = source_metadata(source, title)

    body = parser.markdown()
    if not body.startswith("#"):
        body = f"# {title}\n\n{body}"
    body = aliases_markdown(metadata.get("aliases", [])) + body

    return front_matter(metadata) + body + "\n"


def pdf_source_to_markdown(source: dict, temp_dir: Path) -> str:
    temp_dir.mkdir(parents=True, exist_ok=True)
    source_id = slugify(source["id"])
    pdf_path = temp_dir / f"{source_id}.pdf"
    converted_dir = temp_dir / "converted"

    download_binary(source["url"], pdf_path)
    pdf_to_markdown(pdf_path, converted_dir)

    converted_path = converted_dir / f"{pdf_path.stem}.md"
    body = converted_path.read_text(encoding="utf-8")
    title = source.get("title") or source.get("name") or pdf_path.stem
    metadata = source_metadata(source, title)
    if not body.lstrip().startswith("#"):
        body = f"# {title}\n\n{body}"
    body = aliases_markdown(metadata.get("aliases", [])) + body.lstrip()
    return front_matter(metadata) + body


def load_sources(path: str | Path = config.DATA_SOURCES_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("sources", [])


def ingest_sources(
    sources_path: str | Path = config.DATA_SOURCES_PATH,
    output_dir: str | Path = config.MARKDOWN_DIR,
    overwrite: bool = False,
    limit: int | None = None,
) -> tuple[int, int]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    added = 0
    failed = 0
    sources = load_sources(sources_path)
    if limit:
        sources = sources[:limit]

    for source in sources:
        output_path = output / f"hku_{slugify(source['id'])}.md"
        if output_path.exists() and not overwrite:
            print(f"Skipped existing: {output_path.name}")
            continue

        try:
            source_type = source.get("source_type", "web").lower()
            if source_type == "pdf" or source["url"].lower().split("?", 1)[0].endswith(".pdf"):
                markdown = pdf_source_to_markdown(source, output / ".downloads")
            else:
                html_text = fetch_html(source["url"])
                markdown = source_to_markdown(source, html_text)
            output_path.write_text(markdown, encoding="utf-8")
            print(f"Indexed source: {source['id']} -> {output_path.name}")
            added += 1
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"Failed source {source.get('id', source.get('url'))}: {exc}", file=sys.stderr)
            failed += 1

    return added, failed


def reindex_markdown_documents() -> tuple[int, int]:
    from db.parent_store_manager import ParentStoreManager
    from db.vector_db_manager import VectorDbManager
    from document_chunker import DocumentChuncker

    vector_db = VectorDbManager()
    parent_store = ParentStoreManager()
    chunker = DocumentChuncker()

    vector_db.delete_collection(config.CHILD_COLLECTION)
    vector_db.create_collection(config.CHILD_COLLECTION)
    parent_store.clear_store()

    parent_chunks, child_chunks = chunker.create_chunks()
    if not child_chunks:
        print("No Markdown chunks found to index.")
        return 0, 0

    collection = vector_db.get_collection(config.CHILD_COLLECTION)
    collection.add_documents(child_chunks)
    parent_store.save_many(parent_chunks)
    print(f"Reindexed Markdown documents: {len(parent_chunks)} parent chunks, {len(child_chunks)} child chunks.")
    return len(parent_chunks), len(child_chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch HKU official sources into markdown_docs.")
    parser.add_argument("--sources", default=config.DATA_SOURCES_PATH, help="Path to hku_sources.json.")
    parser.add_argument("--output", default=config.MARKDOWN_DIR, help="Directory to write Markdown files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Markdown files.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of sources for a smoke test.")
    parser.add_argument("--reindex", action="store_true", help="Rebuild Qdrant and parent store from markdown_docs after ingestion.")
    args = parser.parse_args(argv)

    added, failed = ingest_sources(args.sources, args.output, args.overwrite, args.limit)
    if args.reindex:
        reindex_markdown_documents()
    print(f"Done. Added: {added} | Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
