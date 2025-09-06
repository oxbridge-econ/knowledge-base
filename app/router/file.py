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

router = APIRouter(prefix="/file", tags=["file"])


@router.post("")
async def load(files: List[UploadFile] = File(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        files (List[UploadFile]): A list of uploaded files.
        user_id (str): The id of the user.

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
        upsert(user_id, task, "file")
        try:
            if file.content_type == "application/pdf":
                threading.Thread(
                target=load_pdf, args=(content, file.filename, user_id, task)
                ).start()
            elif file.content_type == \
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                threading.Thread(
                    target=load_docx, args=(content, file.filename, user_id, task)
                    ).start()
            elif file.content_type in ["image/png", "image/jpeg"]:
                threading.Thread(
                    target=load_img, args=(content, file.filename, user_id, task)
                ).start()
            else:
                task["status"] = "failed"
                task["error"] = f"Unsupported file type: {file.content_type}"
                upsert(user_id, task, "file")
                tasks.append(task)
                continue
            upload_file_to_azure(content, file.filename, user_id)

        except (FileAlreadyExistsError, Exception)as e: # pylint: disable=broad-except
            task["status"] = "failed"
            task["error"] = str(e)
            upsert(user_id, task, "file")

        tasks.append(task)

    return JSONResponse(content=tasks)

@router.get("")
async def get_azure_files(user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves the list of files uploaded by the user.

    Args:
        user_id (str): The id of the user.

    Returns:
        JSONResponse: A response containing the list of files.
    """
    try:
        files = get_files(user_id)
        return JSONResponse(content=files)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.delete("")
async def delete(user_id: str = Query(None), file_name: str = Query(...),) -> JSONResponse:
    """
    Deletes a file from Azure storage and vector database.

    Args:
        user_id (str): The id of the user.
        file_name (str): The name of the file to be deleted.

    Returns:
        JSONResponse: A response indicating the success or failure of the deletion.
    """
    try:
        result = delete_file(user_id, file_name)
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
