"""This module is responsible for initializing the database connection and creating the necessary tables."""
from pinecone import Pinecone, ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from models.llm import GPTEmbeddings

embeddings = GPTEmbeddings()

pc = Pinecone()
INDEX_NAME = "gmails"
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
