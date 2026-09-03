import os
import shutil
import config
import re
import pymupdf.layout
import pymupdf4llm
from pathlib import Path
import glob
import tiktoken
import unicodedata


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
    "\u935a",
    "\u6fc9",
    "\u5553",
    "\u93b8",
    "\u56e7",
    "\u5d21",
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
    marker_score = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    sequence_score = len(re.findall(
        r"[\u4e00-\u9fff]*[\u935a\u6fc9\u5553\u93b8\u56e7\u5d21\u951b\u9369\u74a7\u6d93\u7ecb\u68e3\ue11f\ufffd][\u4e00-\u9fff]*",
        text,
    ))
    return marker_score + sequence_score


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def _looks_mojibake(text: str) -> bool:
    if not text.strip():
        return False

    score = _mojibake_score(text)
    cjk_count = _cjk_count(text)
    if score >= 8:
        return True
    if cjk_count >= 30 and score / max(cjk_count, 1) > 0.08:
        return True
    return False


def _repair_utf8_read_as_gbk(text: str) -> str:
    """Fix common Chinese PDF mojibake: UTF-8 bytes decoded as GBK/GB18030."""
    run_pattern = re.compile(r"[\u30a0-\u30ff\u4e00-\u9fff\ue000-\uf8ff\uff00-\uffef\u20ac\ufffd]+")

    def repair_run(match):
        original = match.group(0)
        if _mojibake_score(original) == 0:
            return original

        try:
            repaired = original.encode("gb18030", errors="ignore").decode("utf-8", errors="ignore")
        except UnicodeError:
            return original

        if not repaired.strip():
            return original

        original_score = _mojibake_score(original)
        repaired_score = _mojibake_score(repaired)
        repaired_cjk = _cjk_count(repaired)

        if repaired_score < original_score and repaired_cjk > 0:
            return repaired
        return original

    return run_pattern.sub(repair_run, text)


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
    cleaned = md
    for _ in range(2):
        repaired = _repair_utf8_read_as_gbk(cleaned)
        if repaired == cleaned:
            break
        cleaned = repaired
    cleaned = unicodedata.normalize("NFKC", cleaned)
    return cleaned.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")


def pdf_to_markdown(pdf_path, output_dir):
    doc = pymupdf.open(pdf_path)
    md = pymupdf4llm.to_markdown(doc, header=False, footer=False, page_separators=True, ignore_images=True, write_images=False, image_path=None)
    md_cleaned = _clean_pdf_markdown(md)

    if _mojibake_score(md_cleaned) > 5:
        fallback_text = _extract_pdf_text_with_pymupdf(doc)
        fallback_cleaned = _clean_pdf_markdown(fallback_text)
        if fallback_cleaned and _mojibake_score(fallback_cleaned) < _mojibake_score(md_cleaned):
            md_cleaned = fallback_cleaned

    if _looks_mojibake(md_cleaned):
        raise ValueError(
            "PDF text extraction still looks garbled after repair. "
            "Enable OCR or convert this PDF with a better text extraction path before indexing."
        )

    output_path = Path(output_dir) / Path(doc.name).stem
    md_path = Path(output_path).with_suffix(".md")
    md_path.write_bytes(md_cleaned.encode('utf-8'))
    return md_path

def pdfs_to_markdowns(path_pattern, overwrite: bool = False):
    output_dir = Path(config.MARKDOWN_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_paths = []

    for pdf_path in map(Path, glob.glob(path_pattern)):
        md_path = (output_dir / pdf_path.stem).with_suffix(".md")
        if overwrite or not md_path.exists():
            md_path = pdf_to_markdown(pdf_path, output_dir)
        md_paths.append(md_path)
    return md_paths

def estimate_context_tokens(messages: list) -> int:
    try:
        encoding = tiktoken.encoding_for_model("gpt-4")
    except:
        encoding = tiktoken.get_encoding("cl100k_base")
    return sum(len(encoding.encode(str(msg.content))) for msg in messages if hasattr(msg, 'content') and msg.content)
