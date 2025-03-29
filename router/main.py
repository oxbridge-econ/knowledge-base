"""Module for defining the main routes of the API."""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from schema import ReqData
from utils import generate

router = APIRouter()

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

# # @router.post("/followup")
# # def follow_up(req: ReqFollowUp):
# #     """
# #     Handles the follow-up POST request.

# #     Args:
# #         req (ReqFollowUp): The request object containing follow-up data.

# #     Returns:
# #         Response: The response from the follow-up processing function.
# #     """
# #     return followup(req)

# @router.post("/chat/history")
# def retrieve_history(chat_history: ChatHistory):
#     """
#     Endpoint to retrieve chat history.

#     This endpoint handles POST requests to the "/chat/history" URL. It accepts a
#     ChatHistory object as input and returns the chat history.

#     Args:
#         chat_history (ChatHistory): The chat history object containing the details
#         of the chat to be retrieved.

#     Returns:
#         The chat history retrieved by the retrieve_chat_history function.
#     """
#     return get_chat_history(chat_history)

# @router.post("/chat/session")
# def retrieve_session(chat_session: ChatSession):
#     """
#     Retrieve a chat session.

#     Args:
#         chat_session (ChatSession): The chat session to retrieve.

#     Returns:
#         ChatSession: The retrieved chat session.
#     """
#     return get_chat_session(chat_session)

# @router.post("/chat/history/clear")
# def clear_history(chat_history: ChatHistory):
#     """
#     Clears the chat history.

#     Args:
#         chat_history (ChatHistory): The chat history object to be cleared.

#     Returns:
#         The result of the clear_chat_history function.
#     """
#     return clear_chat(chat_history)
