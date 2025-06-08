"""Module for defining the main routes of the API."""
from io import BytesIO

from PIL import Image
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from controllers.loader import extract_text_from_image

router = APIRouter(prefix="/extract", tags=["extract"])

@router.post("/figure")
async def load(file: UploadFile = File(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    content = await file.read()
    text = extract_text_from_image(Image.open(BytesIO(content)))
    return JSONResponse(content={"text": text})
