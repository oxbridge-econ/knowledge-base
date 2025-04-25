"""This module is responsible for initializing the database connection and creating the necessary tables."""
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from models.llm import EmbeddingsModel

embeddings = EmbeddingsModel("all-MiniLM-L6-v2")

pc = Pinecone()
INDEX_NAME = "mails"
if not pc.has_index(INDEX_NAME):
    pc.create_index(
        name=INDEX_NAME,
        dimension=len(embeddings.embed_query("hello")),
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        ) 
    )
index = pc.Index(INDEX_NAME)
vectorstore = PineconeVectorStore(index=index, embedding=embeddings)