"""Module for defining the main routes of the API."""
import uuid
import threading
from venv import logger
from typing import List
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from controllers.utils import upsert
from controllers.loader import (
    load_docx, load_pdf,
    load_img,
    FileAlreadyExistsError,
    upload_file_to_azure, get_files, delete_file)
from schema import task_states

router = APIRouter(prefix="/file", tags=["file"])


@router.post("")
async def load(files: List[UploadFile] = File(...), email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    if len(files)  > 10:
        return JSONResponse(status_code=400,
            content={"error": "Too many files uploaded. Please upload up to 10 files."}
        )
    tasks = []
    for file in files:
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

            if file.content_type == "application/pdf":
                threading.Thread(
                target=load_pdf, args=(content, file.filename,
                email, task)
                ).start()
            elif file.content_type == \
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                threading.Thread(
                    target=load_docx, args=(content, file.filename, email, task)
                    ).start()
            elif file.content_type in ["image/png", "image/jpeg"]:
                threading.Thread(
                    target=load_img, args=(content, file.filename, email, task)
                ).start()
            else:
                task["status"] = "failed"
                task["error"] = f"Unsupported file type: {file.content_type}"
                task_states[task["id"]] = "Failed"
                upsert(email, task)
                tasks.append(task)
                continue
            upload_file_to_azure(content, file.filename, email)

        except (FileAlreadyExistsError, Exception)as e: # pylint: disable=broad-except
            task["status"] = "failed"
            task["error"] = str(e)
            task_states[task["id"]] = "Failed"
            upsert(email, task)

        tasks.append(task)

    return JSONResponse(content=tasks)

@router.get("")
async def get_azure_files(email: str = Query(...)) -> JSONResponse:
    """
    Retrieves the list of files uploaded by the user.

    Args:
        email (str): The email of the user.

    Returns:
        JSONResponse: A response containing the list of files.
    """
    try:
        files = get_files(email)
        return JSONResponse(content=files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.delete("")
async def delete(email: str = Query(...), file_name: str = Query(...),) -> JSONResponse:
    """
    Deletes a file from Azure storage and vector database.

    Args:
        email (str): The email of the user.
        file_name (str): The name of the file to be deleted.

    Returns:
        JSONResponse: A response indicating the success or failure of the deletion.
    """
    try:
        result = delete_file(email, file_name)

        if result["success"]:
            return JSONResponse(
                status_code=200,
                content=result
            )
        return JSONResponse(
            status_code=404 if "not found" in result["error"].lower() else 500,
            content=result
        )

    except Exception as e:
        logger.error("Error in delete endpoint: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
