"""Module to interact with AstraDB collection using AstraDBVectorStore."""
import os
import re
import time
from venv import logger
import tiktoken
import langchain_astradb
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_astradb import AstraDBVectorStore

def token_length(text):
    """
    Calculates length of the encoded text using tokenizer for "text-embedding-3-small" model.

    Args:
        text (str): The input text to be tokenized and measured.

    Returns:
        int: The length of the encoded text.
    """
    tokenizer = tiktoken.encoding_for_model("text-embedding-3-small")
    return len(tokenizer.encode(text))

class VectorStore(AstraDBVectorStore):
    """
    VectorStore class that extends AstraDBVectorStore to interact with a specific collection.

    Attributes:
        collection (str): The name of the collection to interact with. Defaults to "FinFast_China".

    Methods:
        __init__(collection="article"): Initializes VectorStore with collection name,
                                              GPTEmbeddings for embedding, and API credentials.
    """
    def __init__(self, collection_name="documents"):
        super().__init__(
            namespace="default_keyspace",
            collection_name=collection_name,
            token=os.environ["ASTRA_DB_APPLICATION_TOKEN"],
            api_endpoint=os.environ["ASTRA_DB_API_ENDPOINT"],
            autodetect_collection=True)

    def add_documents_with_retry(self, chunks, ids, max_retries=3):
        """
        Attempts to add documents to the vstore with a specified number of retries.

        Parameters:
        chunks (list): The list of document chunks to be added.
        ids (list): The list of document IDs corresponding to the chunks.
        max_retries (int, optional): The maximum number of retry attempts. Default is 3.

        Raises:
        Exception: If the operation fails after the maximum number of retries, the exception is logged.
        """
        for attempt in range(max_retries):
            try:
                self.add_documents(chunks, ids=ids)
            except (ConnectionError, TimeoutError, langchain_astradb.vectorstores.AstraDBVectorStoreError) as e:
                for chunk in chunks:
                    url_pattern = r'https?://[^\s]+'
                    chunk.page_content = re.sub(url_pattern, '[URL]', chunk.page_content)
                logger.info("Attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(10)
                else:
                    logger.error("Max retries reached. Operation failed.")
                    logger.error(ids)
    
    def upload(self, documents):
        """
        Splits the provided documents into smaller chunks using a text splitter and uploads them to the vector store.

        Args:
            documents (List[Document]): A list of Document objects to be uploaded.

        Process:
            - Splits each document into chunks based on specified chunk size and overlap.
            - Generates unique IDs for each chunk by combining the original document ID and chunk index.
            - Uploads the chunks to the vector store with retry logic.

        Raises:
            ValueError: If there is an error during the document upload process.

        Logs:
            Errors encountered during the upload process are logged.
        """
        try:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=2000,  # or 1500, depending on your needs
                chunk_overlap=200,
                length_function=token_length,
                is_separator_regex=False,
                separators = ["\n\n", "\n", "\t", "\\n", "\r\n\r\n", " ", ".", ","]
            )
            chunks = text_splitter.split_documents(documents)
            ids = []
            for index, chunk in enumerate(chunks):
                _id = f"{chunk.metadata['id']}-{str(index)}"
                ids.append(_id)
            self.add_documents_with_retry(documents, ids)
        except ValueError as e:
            logger.error("Error adding documents to vectorstore: %s", e)