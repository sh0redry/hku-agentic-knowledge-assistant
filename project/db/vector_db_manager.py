import config
import json
import pickle
import shutil
import sqlite3
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse, RetrievalMode
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


class VectorDbManager:
    __client: QdrantClient
    __dense_embeddings: HuggingFaceEmbeddings
    __sparse_embeddings: FastEmbedSparse

    def __init__(self):
        self.__client = QdrantClient(path=config.QDRANT_DB_PATH)
        self.__dense_embeddings = HuggingFaceEmbeddings(model_name=config.DENSE_MODEL)
        self.__sparse_embeddings = FastEmbedSparse(model_name=config.SPARSE_MODEL)

    def create_collection(self, collection_name):
        vector_size = len(self.__dense_embeddings.embed_query("test"))
        expected_meta = {"dense_model": config.DENSE_MODEL, "vector_size": vector_size}
        if not self.__client.collection_exists(collection_name):
            print(f"Creating collection: {collection_name}...")
            self._create_collection_with_size(collection_name, vector_size)
            self._save_embedding_meta(collection_name, expected_meta)
            print(f"Collection created: {collection_name}")
            return

        existing_size = self._get_collection_vector_size(collection_name)
        stored_size = self._get_stored_vector_size(collection_name)
        existing_meta = self._load_embedding_meta(collection_name)
        should_recreate = (
            existing_meta != expected_meta
            or (existing_size is not None and existing_size != vector_size)
            or (stored_size is not None and stored_size != vector_size)
        )

        if should_recreate:
            previous = stored_size or existing_size or existing_meta.get("vector_size", "unknown")
            print(
                f"Embedding configuration changed from {previous} to {vector_size}. "
                f"Recreating collection: {collection_name}..."
            )
            self.delete_collection(collection_name)
            self._remove_local_collection_files(collection_name)
            self._create_collection_with_size(collection_name, vector_size)
            self._save_embedding_meta(collection_name, expected_meta)
            print(f"Collection recreated: {collection_name}")
            return

        print(f"Collection already exists: {collection_name}")

    def _create_collection_with_size(self, collection_name, vector_size):
        self.__client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            sparse_vectors_config={config.SPARSE_VECTOR_NAME: qmodels.SparseVectorParams()},
        )

    def _embedding_meta_path(self, collection_name):
        return Path(config.QDRANT_DB_PATH) / f"{collection_name}_embedding.json"

    def _load_embedding_meta(self, collection_name):
        path = self._embedding_meta_path(collection_name)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Warning: could not read embedding metadata: {e}")
            return {}

    def _save_embedding_meta(self, collection_name, metadata):
        path = self._embedding_meta_path(collection_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def _local_collection_path(self, collection_name):
        return Path(config.QDRANT_DB_PATH) / "collection" / collection_name

    def _remove_local_collection_files(self, collection_name):
        path = self._local_collection_path(collection_name).resolve()
        root = (Path(config.QDRANT_DB_PATH) / "collection").resolve()
        if root not in path.parents or not path.exists():
            return
        try:
            shutil.rmtree(path)
        except Exception as e:
            print(f"Warning: could not remove local collection files: {e}")

    def _get_stored_vector_size(self, collection_name):
        sqlite_path = self._local_collection_path(collection_name) / "storage.sqlite"
        if not sqlite_path.exists():
            return None

        try:
            db_uri = sqlite_path.as_posix()
            with sqlite3.connect(f"file:{db_uri}?mode=ro", uri=True) as conn:
                row = conn.execute("select point from points limit 1").fetchone()
            if not row:
                return None

            point = pickle.loads(row[0])
            vector = getattr(point, "vector", None)
            dense_vector = vector.get("") if isinstance(vector, dict) else vector
            return len(dense_vector) if dense_vector is not None else None
        except Exception as e:
            print(f"Warning: could not inspect stored vector size: {e}")
            return None

    def _get_collection_vector_size(self, collection_name):
        try:
            vectors = self.__client.get_collection(collection_name).config.params.vectors
            if hasattr(vectors, "size"):
                return vectors.size
            if isinstance(vectors, dict) and vectors:
                first_vector = next(iter(vectors.values()))
                return getattr(first_vector, "size", None)
        except Exception as e:
            print(f"Warning: could not inspect collection vector size: {e}")
        return None

    def count_documents(self, collection_name):
        if not self.__client.collection_exists(collection_name):
            return 0
        try:
            return self.__client.count(collection_name, exact=True).count
        except Exception as e:
            print(f"Warning: could not count collection {collection_name}: {e}")
            return 0

    def delete_collection(self, collection_name):
        try:
            if self.__client.collection_exists(collection_name):
                print(f"Removing existing Qdrant collection: {collection_name}")
                self.__client.delete_collection(collection_name)
                self._remove_local_collection_files(collection_name)
        except Exception as e:
            print(f"Warning: could not delete collection {collection_name}: {e}")

    def get_collection(self, collection_name) -> QdrantVectorStore:
        try:
            return QdrantVectorStore(
                client=self.__client,
                collection_name=collection_name,
                embedding=self.__dense_embeddings,
                sparse_embedding=self.__sparse_embeddings,
                retrieval_mode=RetrievalMode.HYBRID,
                sparse_vector_name=config.SPARSE_VECTOR_NAME,
            )
        except Exception as e:
            print(f"Unable to get collection {collection_name}: {e}")
