"""This module is responsible for initializing the database connection and creating the necessary tables."""
# import faiss
from pinecone import Pinecone, ServerlessSpec
# from langchain_community.vectorstores import FAISS
# from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_pinecone import PineconeVectorStore
from models.llm import EmbeddingsModel

embeddings = EmbeddingsModel("all-MiniLM-L6-v2")

# vectorstore = FAISS(
#     embedding_function=embeddings,
#     index=faiss.IndexFlatL2(len(embeddings.embed_query("hello world"))),
#     docstore=InMemoryDocstore(),
#     index_to_docstore_id={}
# )

pc = Pinecone()
index_name = "mails"
embedding_dim = len(embeddings.embed_query("hello world"))
if not pc.has_index(index_name):
    pc.create_index(
        name=index_name,
        dimension=embedding_dim, # Replace with your model dimensions
        metric="cosine", # Replace with your model metric
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        ) 
    )
index = pc.Index(index_name)
vectorstore = PineconeVectorStore(index=index, embedding=embeddings)