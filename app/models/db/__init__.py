"""This module is responsible for initializing the database connection and creating the necessary tables."""
import faiss
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
# from langchain_chroma import Chroma
from models.llm import EmbeddingsModel

embeddings = EmbeddingsModel("all-MiniLM-L6-v2")

index = faiss.IndexFlatL2(len(embeddings.embed_query("hello world")))
print(index)

vectorstore = FAISS(
    embedding_function=embeddings,
    index=index,
    docstore=InMemoryDocstore(),
    index_to_docstore_id={}
)