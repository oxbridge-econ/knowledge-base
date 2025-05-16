"""Module for defining the main routes of the API."""
import threading
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services import GmailService
from schema import MailReqData

router = APIRouter(prefix="/service", tags=["mail"])

@router.post("/gmail")
def collect(body: MailReqData) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    service = GmailService(body.email)
    threading.Thread(target=service.collect, args=[body.query]).start()
    return JSONResponse(content={"message": "Mail collection in progress."})

@router.get("/gmail")
def get(body: MailReqData) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    service = GmailService(body.email)
    result = service.get(body.query, body.query.max_results)
    return JSONResponse(content = result)
