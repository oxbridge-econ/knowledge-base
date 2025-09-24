"""Module for defining the main routes of the API."""
import uuid
from venv import logger
from typing import List, Dict, Any
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from services.file import FileService, FileAlreadyExistsError

router = APIRouter(prefix="/file", tags=["file"])


@router.post("")
async def upload_files(files: List[UploadFile] = File(...),
                    user_id: str = Query(None)) -> JSONResponse:
    """
    Upload and process multiple files.
    
    Args:
        files (List[UploadFile]): List of uploaded files
        user_id (str): User ID
        
    Returns:
        JSONResponse: List of task information for each file
    """
    if len(files) > 10:
        return JSONResponse(
            status_code=400,
            content={"error": "Too many files uploaded. Please upload up to 10 files."}
        )

    tasks = []
    for file in files:
        try:
            content = await file.read()
            task = {
                "id": str(uuid.uuid4()),
                "status": "pending",
                "service": "file",
                "type": "manual"
            }

            # Create service instance and process file
            service = FileService(user_id, task)
            result = service.process_file(content, file.filename, file.content_type)
            tasks.append(result)

        except (FileAlreadyExistsError, ValueError) as e:
            task["status"] = "failed"
            task["error"] = str(e)
            tasks.append(task)
        except Exception as e: # pylint: disable=broad-exception-caught
            logger.error("Error processing file %s: %s", file.filename, e)
            task = {
                "id": str(uuid.uuid4()),
                "status": "failed",
                "error": str(e),
                "service": "file",
                "type": "manual"
            }
            tasks.append(task)

    return JSONResponse(content=tasks)

@router.get("")
async def get_user_files(user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieve list of files uploaded by the user.
    
    Args:
        user_id (str): User ID
        
    Returns:
        JSONResponse: List of file metadata
    """
    try:
        service = FileService(user_id)
        files = service.get_files()
        return JSONResponse(content=files)
    except Exception as e: # pylint: disable=broad-exception-caught
        logger.error("Error retrieving files for user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("")
async def delete_user_file(user_id: str = Query(None), file_name: str = Query(...)) -> JSONResponse:
    """
    Delete a file from storage and vector database.
    
    Args:
        user_id (str): User ID
        file_name (str): Name of file to delete
        
    Returns:
        JSONResponse: Deletion result
    """
    try:
        service = FileService(user_id)
        result = service.delete_file(file_name)

        if result["success"]:
            return JSONResponse(status_code=200, content=result)
        return JSONResponse(
            status_code=404 if "not found" in result["error"].lower() else 500,
            content=result
        )
    except Exception as e: # pylint: disable=broad-exception-caught
        logger.error("Error in delete endpoint: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
