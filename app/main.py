"""Module to handle the main FastAPI application and its endpoints."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router import service, file
from schema import task_states

# SECRET_KEY = "your-secret-key"
# ALGORITHM = "HS256"

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.INFO)

app = FastAPI(docs_url="/")

app.include_router(service.router)
app.include_router(file.router)

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
