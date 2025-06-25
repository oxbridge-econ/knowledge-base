"""Module to handle the main FastAPI application and its endpoints."""
import logging

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from schema import task_states
from router import gmail, file, extract
from models.db import MongodbClient

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.INFO)

app = FastAPI(docs_url="/")

app.include_router(gmail.router)
app.include_router(file.router)
app.include_router(extract.router)

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/_health")
def health():
    """
    Returns the health status of the application.

    :return: A string "OK" indicating the health status.
    """
    return "OK"

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    """
    Retrieve the status of a task by its ID.

    Args:
        task_id (str): The unique identifier of the task.

    Returns:
        dict: A dictionary containing the task ID and its status. If the task ID is not found,
              the status will be "NOT_FOUND".
    """
    status = task_states.get(task_id, "NOT_FOUND")
    return {"task_id": task_id, "status": status}

@app.get("/tasks/{task_type}")
async def get_tasks(task_type: str, email: str = Query(...)) -> JSONResponse:
    """
    Retrieve tasks of a specific type for a given user email.

    Args:
        task_type (str): The type of tasks to retrieve (e.g., 'todo', 'inprogress', etc.).
        email (str): The email address of the user whose tasks are to be fetched. This is expected as a query parameter.

    Returns:
        dict: A dictionary containing the list of tasks associated with the provided email and task type.

    Raises:
        HTTPException: If the query parameters are invalid or if there is an error accessing the database.

    Note:
        The function assumes that `MongodbClient` is a properly initialized MongoDB client and that the relevant collections exist.
    """
    tasks = MongodbClient["task"][task_type].find_one({"_id": email})
    if tasks:
        del tasks["_id"]
    else:
        tasks = []
    return JSONResponse(content=tasks, status_code=200)
