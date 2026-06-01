import os
import shutil
import config
import re
import pymupdf.layout
import pymupdf4llm
from pathlib import Path
import glob
import tiktoken


def clear_directory_contents(directory: Path) -> None:
    """Delete everything under directory but not the directory itself (safe for Docker volume / bind mount roots)."""
    directory = Path(directory)
    if not directory.is_dir():
        return
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


os.environ["TOKENIZERS_PARALLELISM"] = "false"

MOJIBAKE_MARKERS = (
    "\u951b",
    "\u9369",
    "\u74a7",
    "\u6d93",
    "\u7ecb",
    "\u68e3",
    "\u6b10",
    "\ue11f",
    "\ufffd",
)


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def _repair_utf8_read_as_gbk(text: str) -> str:
    """Fix common Chinese PDF mojibake: UTF-8 bytes decoded as GBK/GB18030."""
    try:
        repaired = text.encode("gb18030", errors="ignore").decode("utf-8", errors="ignore")
    except UnicodeError:
        return text

    if not repaired.strip():
        return text

    original_score = _mojibake_score(text)
    repaired_score = _mojibake_score(repaired)
    original_cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    repaired_cjk = len(re.findall(r"[\u4e00-\u9fff]", repaired))

    if repaired_score < original_score and repaired_cjk >= max(1, original_cjk // 2):
        return repaired
    return text


def _extract_pdf_text_with_pymupdf(doc) -> str:
    pages = []
    for page in doc:
        text = page.get_text("text")
        if not text.strip() and os.environ.get("ENABLE_PDF_OCR", "false").lower() == "true":
            try:
                textpage = page.get_textpage_ocr(language=os.environ.get("PDF_OCR_LANGUAGE", "chi_sim+eng"))
                text = page.get_text("text", textpage=textpage)
            except Exception as exc:
                print(f"OCR fallback failed on page {page.number + 1}: {exc}")
        if text.strip():
            pages.append(f"{text.strip()}\n\n--- end of page.page_number={page.number + 1} ---")
    return "\n\n".join(pages)


def _clean_pdf_markdown(md: str) -> str:
    repaired = _repair_utf8_read_as_gbk(md)
    return repaired.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")


def pdf_to_markdown(pdf_path, output_dir):
    doc = pymupdf.open(pdf_path)
    md = pymupdf4llm.to_markdown(doc, header=False, footer=False, page_separators=True, ignore_images=True, write_images=False, image_path=None)
    md_cleaned = _clean_pdf_markdown(md)

    if _mojibake_score(md_cleaned) > 5:
        fallback_text = _extract_pdf_text_with_pymupdf(doc)
        fallback_cleaned = _clean_pdf_markdown(fallback_text)
        if fallback_cleaned and _mojibake_score(fallback_cleaned) < _mojibake_score(md_cleaned):
            md_cleaned = fallback_cleaned

    output_path = Path(output_dir) / Path(doc.name).stem
    Path(output_path).with_suffix(".md").write_bytes(md_cleaned.encode('utf-8'))

def pdfs_to_markdowns(path_pattern, overwrite: bool = False):
    output_dir = Path(config.MARKDOWN_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in map(Path, glob.glob(path_pattern)):
        md_path = (output_dir / pdf_path.stem).with_suffix(".md")
        if overwrite or not md_path.exists():
            pdf_to_markdown(pdf_path, output_dir)

def estimate_context_tokens(messages: list) -> int:
    try:
        encoding = tiktoken.encoding_for_model("gpt-4")
    except:
        encoding = tiktoken.get_encoding("cl100k_base")
    return sum(len(encoding.encode(str(msg.content))) for msg in messages if hasattr(msg, 'content') and msg.content)
