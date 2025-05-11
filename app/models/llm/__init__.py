"""Module for OpenAI model and embeddings."""
from typing import List
from langchain.embeddings.base import Embeddings
from sentence_transformers import SentenceTransformer
from openai import AzureOpenAI
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings


class GPTModel(AzureChatOpenAI):
    """
    GPTModel class that extends AzureChatOpenAI.

    This class initializes a GPT model with specific deployment settings and a callback function.

    Attributes:
        callback (function): The callback function to be used with the model.

    Methods:
        __init__(callback):
            Initializes the GPTModel with the specified callback function.
    """
    def __init__(self):
        super().__init__(
        deployment_name="gpt-4o",
        streaming=True, temperature=0)

class GPTEmbeddings(AzureOpenAIEmbeddings):
    """
    GPTEmbeddings class that extends AzureOpenAIEmbeddings.

    This class is designed to handle embeddings using GPT model provided by Azure OpenAI services.

    Attributes:
        Inherits all attributes from AzureOpenAIEmbeddings.

    Methods:
        Inherits all methods from AzureOpenAIEmbeddings.
    """

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
            model_name (str): The name of the model to be used for embedding.
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

client = AzureOpenAI()