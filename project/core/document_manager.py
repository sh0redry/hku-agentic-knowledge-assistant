from pathlib import Path
import shutil
import unicodedata
import config
from utils import pdfs_to_markdowns, clear_directory_contents, _looks_mojibake

class DocumentManager:

    def __init__(self, rag_system):
        self.rag_system = rag_system
        self.markdown_dir = Path(config.MARKDOWN_DIR)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        
    def add_documents(self, document_paths, progress_callback=None):
        if not document_paths:
            print("No documents were provided for upload.")
            return 0, 0
            
        document_paths = [document_paths] if isinstance(document_paths, str) else document_paths
        original_count = len(document_paths)
        document_paths = [p for p in document_paths if p and Path(p).suffix.lower() in [".pdf", ".md"]]
        unsupported_count = original_count - len(document_paths)
        if unsupported_count:
            print(f"Skipped {unsupported_count} unsupported upload(s). Only PDF and Markdown are accepted.")
        
        if not document_paths:
            print("No supported PDF or Markdown files found in the upload.")
            return 0, 0
            
        added = 0
        skipped = 0
        print(f"Received {len(document_paths)} supported document(s) for indexing.")
            
        for i, doc_path in enumerate(document_paths):
            doc_path = Path(doc_path)
            if progress_callback:
                progress_callback((i + 1) / len(document_paths), f"Processing {doc_path.name}")
                
            doc_name = doc_path.stem
            md_path = self.markdown_dir / f"{doc_name}.md"
            parent_id = f"{md_path.stem}_parent_0"
            
            if (
                md_path.exists()
                and self.rag_system.parent_store.exists(parent_id)
                and self.rag_system.vector_db.count_documents(self.rag_system.collection_name) > 0
            ):
                print(f"Skipping already indexed document: {md_path.name}")
                skipped += 1
                continue
                
            try:
                if md_path.exists():
                    print(f"Markdown exists but index may be missing; indexing existing file: {md_path.name}")
                elif doc_path.suffix.lower() == ".md":
                    shutil.copy(doc_path, md_path)
                    markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
                    markdown_text = unicodedata.normalize("NFKC", markdown_text)
                    if _looks_mojibake(markdown_text):
                        md_path.unlink(missing_ok=True)
                        raise ValueError("Markdown content looks garbled; skipped indexing.")
                    md_path.write_text(markdown_text, encoding="utf-8")
                else:
                    generated_paths = pdfs_to_markdowns(str(doc_path), overwrite=False)
                    if generated_paths:
                        md_path = generated_paths[0]
                    else:
                        raise FileNotFoundError(f"No Markdown was generated for {doc_path}")
                parent_chunks, child_chunks = self.rag_system.chunker.create_chunks_single(md_path)
                
                if not child_chunks:
                    print(f"Skipped {md_path.name}: no child chunks were generated.")
                    skipped += 1
                    continue
                
                collection = self.rag_system.vector_db.get_collection(self.rag_system.collection_name)
                collection.add_documents(child_chunks)
                self.rag_system.parent_store.save_many(parent_chunks)
                print(
                    f"Indexed {md_path.name}: "
                    f"{len(parent_chunks)} parent chunk(s), {len(child_chunks)} child chunk(s)."
                )
                
                added += 1
                
            except Exception as e:
                print(f"Error processing {doc_path}: {e}")
                skipped += 1
            
        return added, skipped
    
    def get_markdown_files(self):
        if not self.markdown_dir.exists():
            return []
        return sorted([p.name.replace(".md", ".pdf") for p in self.markdown_dir.glob("*.md")])
    
    def clear_all(self):
        self.markdown_dir.mkdir(parents=True, exist_ok=True)
        clear_directory_contents(self.markdown_dir)
        
        self.rag_system.parent_store.clear_store()
        self.rag_system.vector_db.delete_collection(self.rag_system.collection_name)
        self.rag_system.vector_db.create_collection(self.rag_system.collection_name)
