"""Module for the Vector Database."""
from typing import List
from langchain_chroma import Chroma
from langchain.embeddings.base import Embeddings
from sentence_transformers import SentenceTransformer

class EmbeddingsModel(Embeddings):
    """
    A model for generating embeddings using SentenceTransformer.

    Attributes:
        model (SentenceTransformer): The SentenceTransformer model used for generating embeddings.
    """
    def __init__(self, model_name: str):
        """
        Initializes the Chroma model with the specified model name.

        Args:
            model_name (str): The name of the model to be used for sentence transformation.
        """
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """
        Embed a list of documents into a list of vectors.

        Args:
            documents (List[str]): A list of documents to be embedded.

        Returns:
            List[List[float]]: A list of vectors representing the embedded documents.
        """
        return self.model.encode(documents).tolist()

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a query string into a list of floats using the model's encoding.

        Args:
            query (str): The query string to be embedded.

        Returns:
            List[float]: The embedded representation of the query as a list of floats.
        """
        return self.model.encode([query]).tolist()[0]

vectorstore = Chroma(
    embedding_function=EmbeddingsModel("all-MiniLM-L6-v2"),
    collection_name="email",
    persist_directory="models/chroma/data"
)

# def create_or_get_collection(collection_name: str):
#     """
#     Creates a new collection or gets an existing collection from the Vector Database.

#     Args:
#         collection_name (str): The name of the collection.

#     Returns:
#         chromadb.Collection: The collection associated with the provided name.
#     """
#     chroma_client = chromadb.PersistentClient(path="models/chroma/data")
#     collection = chroma_client.get_or_create_collection(collection_name)
#     # try:
#     #     collection = chroma_client.create_collection(collection_name)
#     # except chromadb.errors.UniqueConstraintError:
#     #     collection = chroma_client.get_collection(collection_name)
#     return collection
