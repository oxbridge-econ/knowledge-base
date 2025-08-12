"""Module for defining the main routes of the API."""
import uuid
import threading
import zipfile
from venv import logger
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from controllers.utils import upsert
from controllers.loader import (
    load_docx, load_pdf,
    load_img,
    FileAlreadyExistsError,
    upload_file_to_azure, get_files, delete_file, process_zip_file)
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
            task_states[task["id"]] = "Failed"
            upsert(email, task)
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Only PDF, TXT, and DOCX are allowed."
            )
        upload_file_to_azure(content, file.filename, email)
    except FileAlreadyExistsError as e:
        task["status"] = "failed"
        task_states[task["id"]] = "Failed"
        upsert(email, task)
        raise HTTPException(
            status_code=409,  # 409 Conflict status code for duplicate resource
            detail=str(e)
        ) from e

    return JSONResponse(content=task)

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

@router.post("/upload-folder")
async def upload_folder(file: UploadFile = File(...), email: str = Query(...)) -> JSONResponse:
    """
    Handles folder upload by accepting a ZIP file and processing all contained files.

    Args:
        file (UploadFile): The ZIP file containing the folder contents.
        email (str): The email of the user.

    Returns:
        JSONResponse: A response containing the overall task status and individual file results.
    """
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP files are allowed for folder upload."
        )

    # Create main task for the folder upload
    main_task = {
        "id": f"folder_{str(uuid.uuid4())}",
        "status": "pending",
        "service": "folder",
        "type": "manual",
        "files_processed": 0,
        "total_files": 0,
        "failed_files": [],
        "successful_files": []
    }
    task_states[main_task["id"]] = "Pending"
    upsert(email, main_task)
    try:
        content = await file.read()

        # Process files in background thread to avoid blocking
        threading.Thread(
            target=process_zip_file,
            args=(content, email, main_task)
        ).start()

        return JSONResponse(content=main_task)


    except Exception as e: # pylint: disable=broad-except
        main_task["status"] = "failed"
        task_states[main_task["id"]] = "Failed"
        upsert(email, main_task)
        logger.error("Error processing folder upload: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
