"""Module for defining the main routes of the API."""
import uuid
import threading
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from controllers.utils import upsert
from controllers.loader import load_docx, load_pdf, load_img, FileAlreadyExistsError,  upload_file_to_azure
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
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "pending",
        "service": "file",
        "type": "manual"
    }
    task_states[task["id"]] = "Pending"
    upsert(email, task)
    try:
        #check if file already exists
        upload_file_to_azure(content, file.filename, email, file.content_type)

        if file.content_type == "application/pdf":
            threading.Thread(target=load_pdf, args=(content, file.filename, email, task, file.content_type)).start()
        elif file.content_type == \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            threading.Thread(target=load_docx, args=(content, file.filename, email, task, file.content_type)).start()
        elif file.content_type in ["image/png", "image/jpeg"]:
            threading.Thread(target=load_img, args=(content, file.filename, email, task, file.content_type)).start()
        else:
            task["status"] = "failed"
            task_states[task["id"]] = "Failed"
            upsert(email, task)
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only PDF, TXT, and DOCX are allowed."
            )
    except FileAlreadyExistsError as e:
        task["status"] = "failed"
        task_states[task["id"]] = "Failed"
        upsert(email, task)
        raise HTTPException(
            status_code=409,  # 409 Conflict status code for duplicate resource
            detail=str(e)
        ) from e

    return JSONResponse(content=task)

