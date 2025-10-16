# pylint: disable=duplicate-code
"""Module for defining the main routes of the API."""
import threading
import uuid
from venv import logger
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pymongo import DESCENDING
from pymongo.errors import PyMongoError
from services import GmailService, get_user_credentials, delete_user
from schema import EmailFilter, DocsReq
from models.db import MongodbClient, cosmos_collection
from controllers.utils import (upsert, generate_query_hash, check_duplicate_query,
    extract_essential_query_fields, process_query_update, prepare_query_for_storage
)

SERVICE = "gmail"
router = APIRouter(prefix="/service/gmail", tags=[SERVICE])
collection = MongodbClient[SERVICE]["user"]

@router.get("")
def validate(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service = SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    return JSONResponse(content={"valid": True})

@router.delete("")
def delete(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Deletes a user's email entry from the service.

    Args:
        email (str): The email address to delete. Required as a query parameter.
        user_id (str, optional): The user ID associated with the email.
            If not provided, defaults to the email.

    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful.
            - If the deletion count is not 1, returns {"valid": False} with status code 401.
            - Otherwise, returns {"valid": True}.
    """
    if user_id is None:
        user_id = email
    count = delete_user(service = SERVICE, _id=f"{user_id}/{email}")
    if count != 1:
        return JSONResponse(content={"error": "Failed to delete user"}, status_code=500)
    return JSONResponse(content={"status": "success"}, status_code=200)

@router.post("/preview")
def preview(body: EmailFilter, email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service = SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    service = GmailService(credentials)
    return JSONResponse(content=service.preview(body.model_dump()))

@router.get("/query")
def get_query(email: str = Query(...), user_id: str = Query(None),
              query_id: str = Query(...)) -> JSONResponse:
    """
    Retrieves a specific email query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        query_id (str): The ID of the query to retrieve.

    Returns:
        JSONResponse: A JSON response containing the requested email query.
    """
    if user_id is None:
        user_id = email
    required_fields = [
        "id", "subject", "from_email", "to_email", "cc_email", "has_words", 
        "not_has_words", "before", "after", "max_results", "topics"
    ]
    #check if user exists
    _id = f"{user_id}/{email}"
    user = collection.find_one({"_id": _id})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    # Use aggregation to filter fields at database level
    pipeline = [
        {"$match": {"_id": _id}},
        {"$unwind": "$queries"},
        {"$match": {"queries.id": query_id}},
        {"$project": {
            "_id": 0,
            "query": {
                "$arrayToObject": {
                    "$filter": {
                        "input": {"$objectToArray": "$queries"},
                        "cond": {"$in": ["$$this.k", required_fields]}
                    }
                }
            }
        }}
    ]

    result = list(collection.aggregate(pipeline))
    if not result:
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found for user."},
            status_code=404
        )
    return JSONResponse(content=result[0]["query"], status_code=200)

@router.delete("/query")
def delete_query(email: str = Query(...), user_id: str = Query(None),
                 query_id: str = Query(...)) -> JSONResponse:
    """
    Deletes a specific email query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        query_id (str): The ID of the query to be deleted, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful or not.
    """
    if user_id is None:
        user_id = email
    _id = f"{user_id}/{email}"
    user_doc = collection.find_one(
        {"_id": _id, "queries.id": query_id},
        projection={"queries.$": 1}
    )
    if not user_doc:
        # Check if user exists at all
        user_exists = collection.find_one({"_id": _id}, projection={"_id": 1})
        if not user_exists:
            return JSONResponse(
                content={"error": "User not found."},
                status_code=404
            )
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found."},
            status_code=404
        )
    result = collection.update_one(
        {"_id": _id},
        {"$pull": {"queries": {"id": query_id}}}
    )
    if result.modified_count > 0:
        return JSONResponse(content={"status": "success"}, status_code=200)
    return JSONResponse(content={"error": "Failed to delete query"}, status_code=500)

@router.post("/query")
def update_query(
    body: EmailFilter, email: str = Query(...), user_id: str = Query(None),
        query_id:str = Query(None)) -> JSONResponse:
    """
    Collects Gmail data for a specified user and initiates an asynchronous collection task.

    Args:
        body (EmailQuery): The query parameters for the email collection.
        email (str, optional): The user's email address, provided as a query parameter.

    Returns:
        JSONResponse: 
            - If the user is not found, returns a 404 error with an appropriate message.
            - If the user's credentials are invalid or expired, returns a 401 error.
            - If duplicate query is found, returns the existing query information.
            - Otherwise, starts a background thread to collect emails,
              updates the user's query in the database,
              and returns a JSON response containing the task ID and its initial status.

    Raises:
        None

    Side Effects:
        - Starts a background thread for email collection.
        - Updates or inserts the user's query parameters in the MongoDB collection.
        - Modifies the global `task_states` dictionary with the new task's status.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service = SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    query["id"] = str(uuid.uuid4()) if "id" not in query else query["id"]
    del query["max_results"]
    query_hash = generate_query_hash(query)
    existing_query = check_duplicate_query(collection, email, query_hash, query_id)

    if existing_query:
        essential_fields = extract_essential_query_fields(existing_query)
        return JSONResponse(
            content={
                "message": "Duplicate query detected. Returning existing query.",
                "existing_query": essential_fields
            },
            status_code=200
        )
    task = {
        "id": str(uuid.uuid4()),
        "status": "pending",
        "service": SERVICE,
        "type": "manual",
        "query": query
    }
    service = GmailService(credentials, user_id, email, task)
    if query_id:
        query, result = process_query_update(user_id, email, query_id, query, query_hash)
        if result.modified_count > 0:
            task = {
                "id": str(uuid.uuid4()),
                "status": "pending",
                "service": SERVICE,
                "type": "manual",
                "query": query
            }
            threading.Thread(target=service.collect, args=[query]).start()
            return JSONResponse(
                content={
                    "status": "query updated and collection started",
                    "task": task
                },
                status_code=200
            )
        return JSONResponse(content={"error": "Failed to update query"}, status_code=500)
    storage_query = prepare_query_for_storage(query, query["id"], query_hash)
    storage_query["createdTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    task = {
            "id": str(uuid.uuid4()),
            "status": "pending",
            "service": SERVICE,
            "type": "manual",
            "query": query
        }
    threading.Thread(target=service.collect, args=[storage_query]).start()
    upsert(f"{user_id}/{email}", task, SERVICE)
    return JSONResponse(content=task)

@router.get("/queries")
def get_queries(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves all email queries for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's email queries.
    """
    if user_id is None:
        user_id = email
    _id = f"{user_id}/{email}"
    user = collection.find_one({"_id": _id})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    pipeline = [
        {"$match": {"_id": _id}},
        {"$unwind": "$queries"},
        {"$sort": {"queries.createdTime": -1}},
        {"$group": {
            "_id": "$_id",
            "queries": {"$push": "$queries"}
        }},
        {"$project": {"queries": 1}}
    ]
    result = list(collection.aggregate(pipeline))
    if not result or "queries" not in result[0]:
        return JSONResponse(content=[], status_code=200)

    processed_queries = []
    for query in result[0]["queries"]:
        processed_query = {
            "id": query.get("id", "unknown"),
            "status": (query["task"]["status"] if "task" in
                        query else query.get("status", "unknown")),
            "filters": {
                key: value for key, value in query.items()
                if key in ["subject", "from_email", "to_email", "cc_email",
                          "has_words", "not_has_words", "before", "after",
                          "topics", "has_attachment"]
                and value is not None
            },
            "count": query.get("task", {}).get("count", 0),
            "service": query.get("task", {}).get("service", ""),
            "type": (query.get("task", {}).get("type", "")),
            "createdTime": query.get("createdTime", ""),
            "title": query.get("title", ""),
        }
        processed_queries.append(processed_query)
    return JSONResponse(content=processed_queries, status_code=200)

@router.post("/docs")
def retrieve_docs(
    body: DocsReq, email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves all documents for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's documents.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service = SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)

    _filter = {
        "metadata.userId": user_id,
        "metadata.email": email,
        "metadata.service": SERVICE,
        "metadata.lastModified": { "$gte": datetime.fromtimestamp(
                int((datetime.now() - timedelta(days=30)).timestamp()), tz=timezone.utc) }
    }

    try:
        # results = list(cosmos_collection.find(
        #     filter=_filter,
        #     projection={"metadata.msgId": 1},
        #     sort={"metadata.date": SortMode.ASCENDING},
        #     skip=body.skip or 0,
        #     limit=body.limit or 10,
        #     timeout_ms=200000
        # ))
        results = list(cosmos_collection.find(
            _filter,  # First positional argument
            {"metadata.msgId": 1}  # projection as second positional arg
        ).sort("metadata.date", DESCENDING)
         .skip(body.skip or 0)
         .limit(body.limit or 10))
        messages = [
            {"id": d["metadata"]["msgId"]}
            for d in results
        ]
        service = GmailService(credentials, user_id, email)
        try:
            total = cosmos_collection.count_documents(_filter)
        except PyMongoError as count_error:
            logger.warning("Count failed, using result length: %s", count_error)
            total = len(results)

        result = {
            "docs": service.preview(messages=messages) if len(messages) > 0 else [],
            "skip": body.skip + len(messages),
            "total": total
        }
        return JSONResponse(content=result, status_code=200)
    except PyMongoError as e:
        logger.error(e)
        response = {
            "error": "The read operation timed out"
        }
        return JSONResponse(content=response, status_code=200)

@router.delete("/doc")
def delete_doc(user_id: str = Query(...), thread_id: str = Query(...)) -> JSONResponse:
    """
    Deletes a document from the database based on user ID and thread ID.
    Args:
        user_id (str): The user ID associated with the document. Required as a query parameter.
        thread_id (str): The thread ID of the document to delete. Required as a query parameter.
    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful.
            - If the document is found and deleted, returns {"status": "success", 
              "deleted_count": <count>} with status code 200.
            - If no documents exist for the user, returns {"error": "User not found."} 
              with status code 404.
            - If the user exists but the specific document is not found, returns 
              {"error": "Document not found."} with status code 404.
            - If the deletion operation fails, returns {"error": "Failed to delete document"} 
              or {"error": "The delete operation timed out"} with status code 500.
    Raises:
        None
    Side Effects:
        - Deletes the document(s) from the Cosmos collection where both 
          metadata.userId and metadata.threadId match the provided values.
    """
    try:
        # Check if any documents exist for this user using find_one
        user_filter = {"metadata.userId": user_id}
        user_exists = cosmos_collection.find_one(
            user_filter,
            {"_id": 1}
        )

        if user_exists is None:
            return JSONResponse(
                content={"error": "User not found."},
                status_code=404
            )

        # Build filter to match both userId and threadId
        _filter = {
            "metadata.userId": user_id,
            "metadata.threadId": thread_id
        }

        # Delete the document(s) from Cosmos collection
        delete_result = cosmos_collection.delete_many(_filter)

        if delete_result.deleted_count > 0:
            return JSONResponse(
                content={
                    "status": "success",
                    "deleted_count": delete_result.deleted_count
                },
                status_code=200
            )

        # User exists but specific document not found
        return JSONResponse(
            content={"error": "Document not found."},
            status_code=404
        )

    except PyMongoError as e:
        logger.error("Error while deleting document: %s", e)
        return JSONResponse(
            content={"error": "Failed to delete document"},
            status_code=500
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error deleting document: %s", e)
        return JSONResponse(
            content={"error": "Failed to delete document"},
            status_code=500
        )
