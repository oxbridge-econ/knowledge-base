"""Module to interact with Azure Cosmos DB MongoDB API."""
import os
import time
import re
from venv import logger
from datetime import datetime, timezone
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
import tiktoken
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

# Cosmos DB Connection
COSMOS_CONNECTION_STRING = os.getenv("COSMOS_CONNECTION_STRING")
COSMOS_DB_NAME = os.getenv("COSMOS_DB_NAME", "kb")
COSMOS_COLLECTION_NAME = os.getenv("COSMOS_COLLECTION_NAME", "documents")
COSMOS_INDEX_NAME = os.getenv("COSMOS_INDEX_NAME", "vector_index")

# Initialize Cosmos DB client

cosmos_client = MongoClient(COSMOS_CONNECTION_STRING)
cosmos_db = cosmos_client[COSMOS_DB_NAME]
cosmos_collection = cosmos_db[COSMOS_COLLECTION_NAME]



def token_length(text):
    """Calculate token length using text-embedding-3-small tokenizer."""
    tokenizer = tiktoken.encoding_for_model("text-embedding-3-small")
    return len(tokenizer.encode(text))


class CosmosVectorStore:
    """
    VectorStore class for Azure Cosmos DB with MongoDB API.
    Handles document chunking, embedding generation, and upsert operations.
    """

    def __init__(self, embedding_model):
        """
        Initialize with embedding model (Azure OpenAI).
        
        Args:
            embedding_model: AzureOpenAIEmbeddings instance
        """
        self.collection = cosmos_collection
        self.db_name = COSMOS_DB_NAME
        self.collection_name = COSMOS_COLLECTION_NAME
        self.index_name = COSMOS_INDEX_NAME
        self.embedding_model = embedding_model

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using Azure OpenAI."""
        return self.embedding_model.embed_query(text)

    def add_documents_with_retry(self, chunks: list[Document], ids: list[str],
                                  task: dict, max_retries: int = 3) -> bool:
        """
        Upserts documents to Cosmos DB with retry logic.
        
        Args:
            chunks: List of Document objects with page_content and metadata
            ids: List of document IDs (static for upsert)
            task: Task dict for status tracking
            max_retries: Number of retry attempts
            
        Returns:
            bool: True if successful
        """

        for attempt in range(max_retries):
            try:
                for index, chunk in enumerate(chunks):
                    doc_id = ids[index]

                    # Generate embedding
                    embedding = self._generate_embedding(chunk.page_content)

                    # Upsert document
                    self.collection.update_one(
                        {"_id": doc_id},
                        {
                            "$set": {
                                "content": chunk.page_content,
                                "metadata": chunk.metadata,
                                "embedding": embedding,
                                "updatedAt": datetime.now(timezone.utc)
                            },
                            "$setOnInsert": {
                                "createdAt": datetime.now(timezone.utc)
                            }
                        },
                        upsert=True
                    )

                task["status"] = "succeeded"
                logger.info("✅ Successfully uploaded %d documents to Cosmos DB", len(chunks))
                return True

            except (ConnectionFailure, OperationFailure) as e:
                # Clean URLs from content on error (like Astra implementation)
                for chunk in chunks:
                    url_pattern = r'https?://[^\s]+'
                    chunk.page_content = re.sub(url_pattern, '[URL]', chunk.page_content)

                logger.warning("Attempt %d failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    time.sleep(60)  # Wait before retry
                else:
                    logger.error("Max retries reached. Operation failed.")
                    logger.error("Failed IDs: %s", ids)
                    raise e

        return False

    def upload(self, documents: list[Document], task: dict) -> bool:
        """
        Splits documents into chunks and uploads them to Cosmos DB.
        
        Args:
            documents: List of Document objects
            task: Task dict for tracking
            
        Returns:
            bool: True if successful
        """
        try:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=2000,
                chunk_overlap=200,
                length_function=token_length,
                is_separator_regex=False,
                separators=["\n\n", "\n", "\t", "\\n", "\r\n\r\n", " ", ".", ","]
            )

            chunks = text_splitter.split_documents(documents)
            ids = []

            for index, chunk in enumerate(chunks):
                _id = f"{chunk.metadata['id']}-{str(index)}"
                ids.append(_id)

            return self.add_documents_with_retry(chunks, ids, task)

        except ValueError as e:
            logger.error("Error uploading documents to Cosmos DB: %s", e)
            task["status"] = "failed"
            raise e

    def delete_many(self, filter_query: dict) -> dict:
        """
        Delete documents matching filter.
        
        Args:
            filter_query: MongoDB filter dict
            
        Returns:
            dict: Result with deleted_count
        """
        result = self.collection.delete_many(filter_query)
        return {"deleted_count": result.deleted_count}

    def similarity_search(self, query: str, k: int = 10,
                         filter_conditions: dict = None,
                         ef_search: int = 40) -> list[dict]:
        """
        Perform vector similarity search using Cosmos DB vector search.
        
        Args:
            query: Search query text
            k: Number of results to return
            filter_conditions: MongoDB filter conditions for metadata
            ef_search: HNSW search parameter (higher = more accurate but slower)
            
        Returns:
            list[dict]: Results with content, metadata, and score
        """
        # Generate embedding for query
        query_embedding = self._generate_embedding(query)

        # Build aggregation pipeline
        pipeline = [
            {
                "$search": {
                    "cosmosSearch": {
                        "vector": query_embedding,
                        "path": "embedding",
                        "k": k * 2 if filter_conditions else k,  # Over-fetch if filtering
                        "efSearch": ef_search
                    },
                    "returnStoredSource": True
                }
            }
        ]

        # Add metadata filters if provided
        if filter_conditions:
            pipeline.append({"$match": filter_conditions})

        # Limit results
        pipeline.append({"$limit": k})

        # Project relevant fields
        pipeline.append({
            "$project": {
                "_id": 1,
                "content": 1,
                "metadata": 1,
                "score": {"$meta": "searchScore"}
            }
        })

        # Execute search
        results = list(self.collection.aggregate(pipeline))
        return results


def create_vector_index():
    """
    Creates the vector search index on Cosmos DB collection.
    
    IMPORTANT: Run this ONCE after setting up the database.
    """
    try:
        cosmos_collection.create_index(
            [("embedding", "cosmosSearch")],
            cosmosSearchOptions={
                "kind": "vector-ivf",      # IVF (Inverted File Index)
                "numLists": 100,           # Number of clusters
                "similarity": "COS",        # Cosine similarity
                "dimensions": 1536          # text-embedding-3-small dimensions
            },
            name=COSMOS_INDEX_NAME
        )
        logger.info("✅ Vector index '%s' created successfully", COSMOS_INDEX_NAME)
    except OperationFailure as e:
        if "IndexAlreadyExists" in str(e):
            logger.info("ℹ️  Vector index already exists")
        else:
            logger.error("❌ Error creating vector index: %s", e)
            raise
