"""Module for defining the main routes of the API."""
import threading
import uuid
from datetime import datetime
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from astrapy.constants import SortMode
from services import GmailService, get_user_credentials
from schema import EmailFilter, DocsReq, task_states
from models.db import MongodbClient, astra_collection
from controllers.utils import upsert

router = APIRouter(prefix="/service/gmail", tags=["service"])
collection = MongodbClient["service"]["gmail"]

@router.post("/collect")
def collect(body: EmailFilter, email: str = Query(...)) -> JSONResponse:
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
    credentials = get_user_credentials(email=email)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "pending",
        "service": "gmail",
        "type": "manual",
        "query": query
    }
    service = GmailService(credentials, email, task)
    threading.Thread(target=service.collect, args=[query]).start()
    del query["max_results"]
    # data = {
    #     "_id": email,
    #     "query": query
    # }
    # collection.update_one(
    #     { '_id': email },
    #     { '$set': data },
    #     upsert=True
    # )
    query["id"] = str(uuid.uuid4()) if "id" not in query else query["id"]
    upsert(email, task)
    task_states[task["id"]] = "Pending"
    upsert(email, query, collection=collection, size=10, field="queries")
    return JSONResponse(content=task)

@router.post("/preview")
def preview(body: EmailFilter, email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    credentials = get_user_credentials(email=email)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    service = GmailService(credentials)
    return JSONResponse(content=service.preview(body.model_dump()))

@router.get("/query")
def get_query(email: str = Query(...), query_id: str = Query(...)) -> JSONResponse:
    """
    Retrieves a specific email query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        query_id (str): The ID of the query to retrieve.

    Returns:
        JSONResponse: A JSON response containing the requested email query.
    """
    required_fields = [
        "id", "subject", "from_email", "to_email", "cc_email", "has_words", 
        "not_has_words", "before", "after", "max_results", "topics"
    ]

    #check if user exists
    user = collection.find_one({"_id": email})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    # Use aggregation to filter fields at database level
    pipeline = [
        {"$match": {"_id": email}},
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
def valid(email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    # cred_dict = collection.find_one({"_id": email}, projection={"token": 1, "refresh_token": 1})
    # if cred_dict is None:
    #     return JSONResponse(content={"error": "User not found."}, status_code=404)
    # credentials = Credentials(
    #     token=cred_dict["token"],
    #     refresh_token=cred_dict["refresh_token"],
    #     token_uri="https://oauth2.googleapis.com/token",
    #     client_id=os.environ.get("CLIENT_ID"),
    #     client_secret=os.environ.get("CLIENT_SECRET"),
    #     scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    # )
    credentials = get_user_credentials(email=email)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    return JSONResponse(content={"valid": True})

@router.get("/queries")
def get_queries(email: str = Query(...)) -> JSONResponse:
    """
    Retrieves all email queries for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's email queries.
    """
    # Define the required fields to include in the response
    required_fields = [
        "id", "subject", "from_email", "to_email", "cc_email", "has_words", 
        "not_has_words", "before", "after", "max_results", "topics"
    ]

    pipeline = [
        {"$match": {"_id": email}},
        {"$project": {
            "_id": 0,  # Exclude _id
            "queries": {
                "$map": {
                    "input": "$queries",
                    "as": "query",
                    "in": {
                        "$arrayToObject": {
                            "$filter": {
                                "input": {
                                    "$objectToArray": "$$query"
                                },
                                "cond": {
                                    "$in": ["$$this.k", required_fields]
                                }
                            }
                        }
                    }
                }
            }
        }}
    ]
    queries = []
    if collection.count_documents({"_id": email}) > 0:
        result = list(collection.aggregate(pipeline))
        queries = result[0] if result else {"queries": []}
    return JSONResponse(content=queries, status_code=200)

@router.post("/docs")
def retrieve_docs(body: DocsReq, email: str = Query(...)) -> JSONResponse:
    """
    Retrieves all documents for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's documents.
    """
    credentials = get_user_credentials(email=email)
    _filter = {
        "metadata.userId": email,
        "metadata.type": "gmail"
    }
    results = list(astra_collection.find(
        filter=_filter,
        projection={"metadata.msgId": 1},
        sort={"metadata.date": SortMode.ASCENDING},
        skip=body.skip or 0,
        limit=body.limit or 10
    ))
    messages = [
        {"id": d["metadata"]["msgId"]}
        for d in results
    ]
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    service = GmailService(credentials, email)
    result = {
        "docs": service.preview(messages=messages) if len(messages) > 0 else [],
        "skip": body.skip + len(messages),
        "total": astra_collection.count_documents(
            filter=_filter, upper_bound=1000)
    }
    return JSONResponse(content=result, status_code=200)

@router.delete("/query")
def delete_query(email: str = Query(...), query_id: str = Query(...)) -> JSONResponse:
    """
    Deletes a specific email query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        query_id (str): The ID of the query to be deleted, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful or not.
    """
    #check if the user exists and has the query
    user_doc = collection.find_one(
        {"_id": email, "queries.id": query_id},
        projection={"queries.$": 1}
    )
    if not user_doc:
        # Check if user exists at all
        user_exists = collection.find_one({"_id": email}, projection={"_id": 1})
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
        {"_id": email},
        {"$pull": {"queries": {"id": query_id}}}
    )
    if result.modified_count > 0:
        return JSONResponse(content={"status": "success"}, status_code=200)
    return JSONResponse(content={"error": "Failed to delete query"}, status_code=500)

@router.post("/query")
def post_query(body: EmailFilter, email: str = Query(...)) -> JSONResponse:
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
    credentials = get_user_credentials(email=email)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "pending",
        "service": "gmail",
        "type": "manual",
        "query": query
    }
    query["status"] = task["status"]
    query["service"] = task["service"]
    query["type"] = task["type"]
    query["count"] = 0
    service = GmailService(credentials, email, task)
    threading.Thread(target=service.collect, args=[query]).start()
    del query["max_results"]

    # data = {
    #     "_id": email,
    #     "query": query
    # }
    # collection.update_one(
    #     { '_id': email },
    #     { '$set': data },
    #     upsert=True
    # )
    query["id"] = task["id"]
    upsert(email, task)
    task_states[task["id"]] = "Pending"
    upsert(email, query, collection=collection, size=10, field="queries")
    return JSONResponse(content=task)

@router.put("/query")
def put_query(
    body: EmailFilter, email: str = Query(...), query_id: str = Query(...)
    ) -> JSONResponse:
    """
    Updates an existing email query for a user in the MongoDB collection.

    Args:
        body (EmailFilter): The updated email query data.
        email (str): The user's email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the update was successful or not.
    """
    user = collection.find_one({"_id": email})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    # Check if query exists before updating
    query_exists = collection.find_one(
        {"_id": email, "queries.id": query_id},
        projection={"queries.$": 1}
    )
    if not query_exists:
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found for user."},
            status_code=404
        )

    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    query["createdTime"] = query_exists["queries"][0].get("createdTime")
    query["updatedTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    del query["max_results"]
    # Update the query in the database
    result = collection.update_one(
        {"_id": email, "queries.id": query_id},
        {"$set": {"queries.$": query}}
    )

    if result.modified_count > 0:
        return JSONResponse(content={"status": "success"}, status_code=200)

    return JSONResponse(content={"error": "Failed to update query"}, status_code=500)
