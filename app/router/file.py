"""Module for defining the main routes of the API."""
import uuid
from pathlib import Path
import threading
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from controllers.utils import upsert_task
from controllers.loader import load_docx, load_pdf, load_img
from schema import task_states

router = APIRouter(prefix="/file", tags=["file"])

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg"
}

@router.post("")
async def load(file: UploadFile = File(...), email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    content = await file.read()
    task_id = f"{str(uuid.uuid4())}"
    task = {"id": task_id, "status": "Pending"}
    task_states[task["id"]] = task["status"]
    upsert_task(email, task)
    if file.content_type not in ALLOWED_FILE_TYPES \
        or Path(file.filename).suffix.lower() != ALLOWED_FILE_TYPES.get(file.content_type):
        task["status"] = "Failed"
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF, TXT, and DOCX are allowed."
        )
    elif file.content_type == "application/pdf":
        threading.Thread(target=load_pdf, args=(content, file.filename, email, task)).start()
    elif file.content_type == \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        threading.Thread(target=load_docx, args=(content, file.filename, email, task)).start()
    elif file.content_type in ["image/png", "image/jpeg"]:
        threading.Thread(target=load_img, args=(content, file.filename, email, task)).start()
    return JSONResponse(content=task)
