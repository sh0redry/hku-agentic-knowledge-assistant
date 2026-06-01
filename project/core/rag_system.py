import uuid
import config
from db.vector_db_manager import VectorDbManager
from db.parent_store_manager import ParentStoreManager
from document_chunker import DocumentChuncker
from rag_agent.tools import ToolFactory
from rag_agent.graph import create_agent_graph
from core.observability import Observability
from core.llm_factory import create_chat_model, create_rewrite_model

class RAGSystem:

    def __init__(self, collection_name=config.CHILD_COLLECTION):
        self.collection_name = collection_name
        self.vector_db = VectorDbManager()
        self.parent_store = ParentStoreManager()
        self.chunker = DocumentChuncker()
        self.observability = Observability()
        self.agent_graph = None
        self.thread_id = str(uuid.uuid4())
        self.recursion_limit = config.GRAPH_RECURSION_LIMIT

    def initialize(self):
        self.vector_db.create_collection(self.collection_name)
        collection = self.vector_db.get_collection(self.collection_name)
        self._index_existing_documents_if_empty(collection)

        llm = create_chat_model()
        rewrite_llm = create_rewrite_model()
        tools = ToolFactory(collection).create_tools()
        self.agent_graph = create_agent_graph(llm, tools, collection, rewrite_llm=rewrite_llm)

    def _index_existing_documents_if_empty(self, collection):
        if self.vector_db.count_documents(self.collection_name) > 0:
            return

        parent_chunks, child_chunks = self.chunker.create_chunks()
        if not child_chunks:
            return

        print(f"Indexing {len(child_chunks)} chunks from existing Markdown documents...")
        collection.add_documents(child_chunks)
        self.parent_store.save_many(parent_chunks)

    def get_config(self):
        cfg = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": self.recursion_limit}
        handler = self.observability.get_handler()
        if handler:
            cfg["callbacks"] = [handler]
        return cfg

    def reset_thread(self):
        try:
            self.agent_graph.checkpointer.delete_thread(self.thread_id)
        except Exception as e:
            print(f"Warning: Could not delete thread {self.thread_id}: {e}")
        self.thread_id = str(uuid.uuid4())
