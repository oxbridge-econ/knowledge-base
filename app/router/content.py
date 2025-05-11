"""Module for defining the main routes of the API."""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from schema import ReqData
from utils import generate

router = APIRouter(tags=["content"])

@router.post("/stream")
async def stream(query: ReqData):
    """
    Handles streaming of data based on the provided query.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        StreamingResponse: A streaming response with generated data with type 'text/event-stream'.
    """
    return StreamingResponse(generate(query), media_type='text/event-stream')
