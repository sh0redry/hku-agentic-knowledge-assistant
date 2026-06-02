import os

# --- Directory Configuration ---
_BASE_DIR = os.path.dirname(os.path.dirname(__file__))

MARKDOWN_DIR = os.path.join(_BASE_DIR, "markdown_docs")
PARENT_STORE_PATH = os.path.join(_BASE_DIR, "parent_store")
QDRANT_DB_PATH = os.path.join(_BASE_DIR, "qdrant_db")
DATA_SOURCES_PATH = os.path.join(_BASE_DIR, "project", "data_sources", "hku_sources.json")

# --- Qdrant Configuration ---
CHILD_COLLECTION = os.environ.get("CHILD_COLLECTION", "document_child_chunks_bge_m3")
SPARSE_VECTOR_NAME = "sparse"

# --- Model Configuration ---
DENSE_MODEL = os.environ.get("DENSE_MODEL", "BAAI/bge-m3")
SPARSE_MODEL = os.environ.get("SPARSE_MODEL", "Qdrant/bm25")
SEARCH_SCORE_THRESHOLD = float(os.environ.get("SEARCH_SCORE_THRESHOLD", "0.3"))
DIRECT_SINGLE_QUESTION = os.environ.get("DIRECT_SINGLE_QUESTION", "true").lower() == "true"
DIRECT_RETRIEVAL_LIMIT = int(os.environ.get("DIRECT_RETRIEVAL_LIMIT", "5"))
DIRECT_RETRIEVAL_RETRIES = int(os.environ.get("DIRECT_RETRIEVAL_RETRIES", "4"))
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
LLM_TEMPERATURE = 0
QUERY_REWRITE_PROVIDER = os.environ.get("QUERY_REWRITE_PROVIDER", LLM_PROVIDER).lower()
QUERY_REWRITE_MODEL = os.environ.get("QUERY_REWRITE_MODEL", "qwen2.5:3b-instruct")

# Provider-specific configuration
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# --- Agent Configuration ---
MAX_TOOL_CALLS = int(os.environ.get("MAX_TOOL_CALLS", "5"))
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", "4"))
GRAPH_RECURSION_LIMIT = 50
BASE_TOKEN_THRESHOLD = 2000
TOKEN_GROWTH_FACTOR = 0.9

# --- Text Splitter Configuration ---
CHILD_CHUNK_SIZE = 500
CHILD_CHUNK_OVERLAP = 100
MIN_PARENT_SIZE = 2000
MAX_PARENT_SIZE = 4000
HEADERS_TO_SPLIT_ON = [
    ("#", "H1"),
    ("##", "H2"),
    ("###", "H3")
]

# --- Langfuse Observability ---
LANGFUSE_ENABLED = os.environ.get("LANGFUSE_ENABLED", "false").lower() == "true"
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
