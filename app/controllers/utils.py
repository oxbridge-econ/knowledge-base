"""Module for utility functions related to MongoDB operations."""
import time
from venv import logger
from datetime import datetime
import hashlib
from langchain_core.documents import Document

from openai import RateLimitError
from fastapi.responses import JSONResponse

from openai import RateLimitError, OpenAIError


from models.db import MongodbClient
from models.llm import GPTModel
from controllers.topic import detector

def check_relevance(documents: Document, topics: list[str]) -> list[Document]:
    """
    Checks the relevance of documents list using a detector and returns the relevant documents.

    For each document, the detector is invoked to check its relevance.
    If the verdict is positive, the document is considered relevant and added to the list.
    If a RateLimitError occurs, the method retries up to a maximum number of times,
    waiting between retries. If the maximum retries are reached or other exceptions
    (ValueError, TypeError, KeyError) occur, the document is added to the result list.

    Args:
        documents (list[Document]): A list of Document objects to check for relevance.

    Returns:
        list[Document]:
            A list of Document objects deemed relevant or added as fallback due to errors.
    """
    rel_documents = []
    max_retries = 3
    for document in documents:
        for retry in range(max_retries):
            try:
                is_relevant = detector.invoke(
                    {"document": document, "topics": topics}).model_dump()['verdict']
                if is_relevant:
                    logger.info("Document %s is relevant to the topic.",
                                document.metadata["id"])
                    rel_documents.append(document)
                else:
                    logger.info("Document %s is not relevant to the topic.",
                                document.metadata["id"])
                break  # Success, exit retry loop
            except RateLimitError:
                wait_time = 60
                logger.warning("Rate limit hit. Waiting %ds before retry %d/%d",
                                wait_time, retry+1, max_retries)
                if retry < max_retries - 1:
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries reached for OpenAI API. Skipping document.")
                    # Just add the document without checking relevance as fallback
                    rel_documents.append(document)
            except (ValueError, TypeError, KeyError) as e:
                logger.error("Error checking document relevance: %s", str(e))
                # Add document anyway as fallback
                rel_documents.append(document)
                break
    return rel_documents

def upsert(_id, element, service: str, name: str = "manual") -> None:
    """
    Inserts or updates an element in a MongoDB collection for a given service and name.

    If the element with the specified 'id' exists
    in the collection's array field ('queries' for 'user', 'tasks' otherwise),
    it updates the element's fields (excluding 'id').
    If not, it appends the element to the array,
    maintaining a maximum size (10 for 'queries', 100 for 'tasks').
    Automatically sets 'createdTime' and 'updatedTime' fields.

    Args:
        _id: The unique identifier of the document in the collection.
        element (dict): The element to upsert, must contain an 'id' field.
        service (str): The MongoDB database name.
        name (str): The collection name ('user' or other).

    Returns:
        None
    """
    if name == "user":
        field = "queries"
        size = 10
    else:
        field = "tasks"
        size = 100
    collection = MongodbClient[service][name]
    current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    if "createdTime" not in element:
        element["createdTime"] = current_time
    element["updatedTime"] = current_time
    update_fields = {f"{field}.$.{k}": v for k, v in element.items() if k != "id"}
    result = collection.update_one(
        {
            "_id": _id,
            f"{field}.id": element["id"]
        },
        {
            "$set": update_fields
        },
        upsert=False
    )
    if result.matched_count == 0:
        result = collection.update_one(
            { "_id": _id },
            {
                "$push": { f"{field}": { "$each": [element], "$slice": -size } }
            },
            upsert=True
        )

def generate_query_hash(query_params: dict) -> str:
    """
    Generate a unique hash for query parameters to detect duplicates.
    Uses an allowlist approach with specified fields.
    
    Args:
        query_params (dict): The query parameters dictionary
        include_fields (list): List of fields to include in hash calculation.
                              If None, uses default Gmail query fields.
        
    Returns:
        str: SHA-256 hash of the normalized query parameters
    """
    # Default fields for Gmail queries if not specified
    include_fields = [
        'subject', 'from_email', 'to_email', 'cc_email', 
        'has_words', 'not_has_words', 'before', 'after', 'topics', "has_attachment"
    ]

    # Create a copy and include only specified fields
    normalized_query = {}
    for field in include_fields:
        if field in query_params and query_params[field] is not None:
            value = query_params[field]
            # Sort list values for consistent hashing
            if isinstance(value, list):
                value = sorted(value)
            normalized_query[field] = value

    # Sort keys to ensure consistent hash for same content
    sorted_query = dict(sorted(normalized_query.items()))

    # Convert to string and hash
    query_string = str(sorted_query)
    return hashlib.sha256(query_string.encode()).hexdigest()

def extract_essential_query_fields(query_data: dict) -> dict:
    """
    Extract essential fields from a query for response formatting.
    
    Args:
        query_data (dict): The full query data
        
    Returns:
        dict: Dictionary containing only essential query fields
    """
    essential_fields = [
        "id", "subject", "from_email", "to_email", "cc_email", 
        "has_words", "not_has_words", "before", "after", "topics", "has_attachment",
        "createdTime", "count",
        "status", "service", "type", "title"
    ]

    return {
        field: query_data.get(field)
        for field in essential_fields
        if query_data.get(field) is not None
    }

def check_duplicate_query(collection, email: str,
        query_hash: str, exclude_query_id: str = None) -> dict:
    """
    Check for duplicate queries in the collection.
    
    Args:
        collection: MongoDB collection
        email (str): User email
        query_hash (str): Hash of the query to check
        exclude_query_id (str): Query ID to exclude from duplicate check
        
    Returns:
        dict: Existing query data if duplicate found, None otherwise
    """
    if exclude_query_id:
        # For updates: find queries with same hash but different ID
        match_filter = {
            "_id": email,
            "queries": {
                "$elemMatch": {
                    "hash": query_hash,
                    "id": {"$ne": exclude_query_id}
                }
            }
        }
    else:
        # For new queries: find any query with same hash
        match_filter = {
            "_id": email,
            "queries": {
                "$elemMatch": {
                    "hash": query_hash
                }
            }
        }

    # Use aggregation to get the specific matching query
    pipeline = [
        {"$match": match_filter},
        {"$unwind": "$queries"},
        {"$match": {"queries.hash": query_hash}},
        {"$project": {"query": "$queries", "_id": 0}}
    ]

    if exclude_query_id:
        # Add additional match to exclude the specific query ID
        pipeline.insert(2, {"$match": {"queries.id": {"$ne": exclude_query_id}}})

    result = list(collection.aggregate(pipeline))

    if result:
        return result[0]["query"]
    return None

def generate_query_title(filters: dict) -> str: # pylint: disable=too-many-branches
    """
    Generate a descriptive title for a Gmail query based on its filters using AI.
    
    Args:
        filters (dict): Query filter parameters
        
    Returns:
        str: Generated title for the query
    """
    try:
        # Build filter description
        filter_parts = []
        if filters.get("subject"):
            filter_parts.append(f"Subject: {filters['subject']}")
        if filters.get("from_email"):
            filter_parts.append(f"From: {filters['from_email']}")
        if filters.get("to_email"):
            filter_parts.append(f"To: {filters['to_email']}")
        if filters.get("cc_email"):
            filter_parts.append(f"CC: {filters['cc_email']}")
        if filters.get("has_words"):
            filter_parts.append(f"Keywords: {filters['has_words']}")
        if filters.get("not_has_words"):
            filter_parts.append(f"Exclude: {filters['not_has_words']}")
        if filters.get("before"):
            filter_parts.append(f"Before: {filters['before']}")
        if filters.get("after"):
            filter_parts.append(f"After: {filters['after']}")
        if filters.get("has_attachment"):
            filter_parts.append("With attachments")
        if filters.get("topics") and isinstance(filters["topics"], list) and filters["topics"]:
            filter_parts.append(f"Topics: {', '.join(filters['topics'])}")

        if not filter_parts:
            return "All Emails"

        filter_description = " | ".join(filter_parts)

        # Generate title using GPT
        # pylint: disable=line-too-long
        prompt = f"""Generate a concise, descriptive title (max 60 characters) for a Gmail query with these filters:
{filter_description}

The title should be clear and informative, describing what emails this query would find. Examples:
- "GitHub notifications from oxbridge-econ/finbot"
- "SmartCareers emails to gli@oxbridge-econ.com after May 2025"
- "FinFAST emails about Finance, Economy, AI topics"

Title:"""

        model = GPTModel()
        response = model.invoke(prompt)
        title = response.content.strip().strip('"').strip("'")

        # Ensure title is not too long
        if len(title) > 60:
            title = title[:57] + "..."

        return title

    except (OpenAIError, AttributeError, TypeError, KeyError) as e:
        logger.warning("Failed to generate AI title: %s", str(e))
        # Fallback to simple concatenation
        if filters.get("subject"):
            return f"Subject: {filters['subject'][:40]}..."
        if filters.get("from_email"):
            return f"From: {filters['from_email'][:40]}..."
        if filters.get("to_email"):
            return f"To: {filters['to_email'][:40]}..."
        return "Gmail Query"

def prepare_query_for_storage(query_params: dict, task_id: str, query_hash: str) -> dict:
    """
    Prepare query parameters for storage in the database.
    
    Args:
        query_params (dict): Raw query parameters
        task_id (str): Task identifier
        query_hash (str): Query hash
        
    Returns:
        dict: Formatted query ready for storage
    """
    # Remove max_results as it's not stored
    storage_query = {k: v for k, v in query_params.items() if k != "max_results"}

    storage_query.update({
        "id": task_id,
        "hash": query_hash,
        "task":{
            "status": "pending",
            "service": "gmail",
            "type": "manual",
            "count": 0
        }
    })

    # Generate AI title based on filters
    storage_query["title"] = generate_query_title(storage_query)

    return storage_query

def process_query_update(user_id: str, email: str, query_id: str,
    query_params: dict, query_hash: str) -> JSONResponse:
    """Handle updating an existing query."""
    # Check if query exists
    _id = f"{user_id}/{email}"
    collection = MongodbClient["gmail"]["user"]
    query_exists = collection.find_one(
        {"_id": _id, "queries.id": query_id},
        projection={"queries.$": 1}
    )
    if not query_exists:
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found for user."},
            status_code=404
        )

    storage_query = prepare_query_for_storage(query_params, query_id, query_hash)
    storage_query["createdTime"] = query_exists["queries"][0].get("createdTime")
    storage_query["updatedTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    result = collection.update_one(
        {"_id": _id, "queries.id": query_id},
        {"$set": {"queries.$": storage_query}}
    )
    return storage_query, result
