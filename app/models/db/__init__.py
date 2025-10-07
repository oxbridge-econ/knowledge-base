"""Database module for managing database connections and operations."""
from .mongodb import MongodbClient
# from .astra import VectorStore, astra_collection
from .cosmosdb import CosmosVectorStore, cosmos_collection  # NEW
from ..llm import GPTEmbeddings

# vstore = VectorStore()

embedding_model = GPTEmbeddings(azure_deployment="text-embedding-3-small")

# Initialize Cosmos vector store
vstore = CosmosVectorStore(embedding_model=embedding_model)

__all__ = [
    "MongodbClient",
    "vstore",
    "cosmos_collection"
]
