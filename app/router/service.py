"""Module for defining the main routes of the API."""
import threading
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services import GmailService

from schema import EmailQuery

router = APIRouter(prefix="/service", tags=["mail"])

@router.post("/gmail")
def collect(query: EmailQuery, request: Request) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    service = GmailService(request.headers.get("Google-Token"))
    threading.Thread(target=service.collect, args=[query]).start()
    return JSONResponse(content={"message": "Mail collection in progress."})

@router.get("/gmail")
def get(query: EmailQuery, request: Request) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    service = GmailService(request.headers.get("Google-Token"))
    result = service.get(query, query.max_results)
    return JSONResponse(content = result)
