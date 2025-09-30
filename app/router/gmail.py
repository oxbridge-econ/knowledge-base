"""Module for defining the main routes of the API."""
import threading
import uuid
from venv import logger
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from astrapy.constants import SortMode
from astrapy.exceptions.data_api_exceptions import DataAPITimeoutException
from services import GmailService, get_user_credentials
from schema import EmailFilter, DocsReq
from models.db import MongodbClient, astra_collection
from controllers.utils import (upsert, generate_query_hash, check_duplicate_query,
    extract_essential_query_fields, process_query_update
)

SERVICE = "gmail"
router = APIRouter(prefix="/service/gmail", tags=[SERVICE])
collection = MongodbClient[SERVICE]["user"]

@router.post("/collect")
def collect(body: EmailFilter, email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Collects Gmail data for a specified user and initiates an asynchronous collection task.

    Args:
        body (EmailQuery): The query parameters for the email collection.
        email (str, optional): The user's email address, provided as a query parameter.

    Returns:
        JSONResponse: 
            - If the user is not found, returns a 404 error with an appropriate message.
            - If the user's credentials are invalid or expired, returns a 401 error.
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
    _id = f"{user_id}/{email}"
    credentials = get_user_credentials(service=SERVICE, _id=_id)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "pending",
        "service": SERVICE,
        "type": "manual",
        "query": query
    }
    service = GmailService(credentials, user_id, email, task)
    threading.Thread(target=service.collect, args=[query]).start()
    del query["max_results"]
    query["id"] = str(uuid.uuid4()) if "id" not in query else query["id"]
    upsert(_id, task, SERVICE)
    upsert(_id, query, SERVICE, "user")
    return JSONResponse(content=task)

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

@router.get("/queries")
def get_queries(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves all email queries for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's email queries.
    """
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
        results = list(astra_collection.find(
            filter=_filter,
            projection={"metadata.msgId": 1},
            sort={"metadata.date": SortMode.ASCENDING},
            skip=body.skip or 0,
            limit=body.limit or 10,
            timeout_ms=200000
        ))
        messages = [
            {"id": d["metadata"]["msgId"]}
            for d in results
        ]
        service = GmailService(credentials, user_id, email)
        result = {
            "docs": service.preview(messages=messages) if len(messages) > 0 else [],
            "skip": body.skip + len(messages),
            "total": astra_collection.count_documents(
                filter=_filter, upper_bound=10000, timeout_ms=200000)
        }
        return JSONResponse(content=result, status_code=200)
    except DataAPITimeoutException as e:
        logger.error(e)
        response = {
            "error": "The read operation timed out"
        }
        return JSONResponse(content=response, status_code=200)

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
    task = {
            "id": str(uuid.uuid4()),
            "status": "pending",
            "service": SERVICE,
            "type": "manual",
            "query": query
        }
    threading.Thread(target=service.collect, args=[query]).start()
    upsert(f"{user_id}/{email}", task, SERVICE)
    return JSONResponse(content=task)
