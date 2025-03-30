"""Module for defining the main routes of the API."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from controllers import mail

router = APIRouter(prefix="/mail", tags=["Mail"])

@router.post("")
def collect():
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    mail.collect()
    return JSONResponse(content={"message": "Mail collected successfully."})

@router.get("")
def get():
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    result = mail.get()
    return JSONResponse(content= result)
