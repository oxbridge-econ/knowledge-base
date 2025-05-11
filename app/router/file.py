"""Module for defining the main routes of the API."""
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from controllers.loader import load_pdf

router = APIRouter(prefix="/file", tags=["file"])

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"
}

@router.post("")
async def preview(file: UploadFile = File(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    content = await file.read()
    result = []
    if file.content_type not in ALLOWED_FILE_TYPES \
        or Path(file.filename).suffix.lower() != ALLOWED_FILE_TYPES.get(file.content_type):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF, TXT, and DOCX are allowed."
        )
    elif file.content_type == "application/pdf":
        result = load_pdf(content, file.filename)
    return JSONResponse(content=result)
