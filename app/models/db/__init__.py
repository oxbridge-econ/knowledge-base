"""This module is responsible for initializing the database connection and creating the necessary tables."""
import faiss
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from models.llm import EmbeddingsModel

embeddings = EmbeddingsModel("all-MiniLM-L6-v2")

vectorstore = FAISS(
    embedding_function=embeddings,
    index=faiss.IndexFlatL2(len(embeddings.embed_query("hello world"))),
    docstore=InMemoryDocstore(),
    index_to_docstore_id={}
)