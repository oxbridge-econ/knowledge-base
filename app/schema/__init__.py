"""Module containing the data models for the application."""
from typing import Optional, List
from pydantic import BaseModel, Field

class ReqData(BaseModel):
    """
    RequestData is a Pydantic model that represents the data structure for a request.

    Attributes:
        query (str): The query string provided by the user.
        chat_id (str): The unique identifier for the chat session.
        user_id (str): The unique identifier for the user.
        web (Optional[bool]): A flag indicating if the request is from the web. Defaults to False.
    """
    query: str
    id: Optional[List[str]] = []
    site: Optional[List[str]] = []
    chat_id: str
    user_id: str
    web: Optional[bool] = False

class ReqFollowUp(BaseModel):
    """
    RequestFollowUp is a Pydantic model that represents a request for follow-up.

    Attributes:
        query (str): The query string that needs follow-up.
        contexts (list[str]): A list of context strings related to the query.
    """
    query: str
    contexts: list[str]

class FollowUpQ(BaseModel):
    """
    FollowUpQ model to represent a follow-up question based on context information.

    Attributes:
        question (list[str]): A list of follow-up questions based on context information.
    """
    questions: list[str] = Field(..., description="3 Follow up questions based on context.")

class ChatHistory(BaseModel):
    """
    ChatHistory model representing a chat session.

    Attributes:
        chat_id (str): The unique identifier for the chat session.
        user_id (str): The unique identifier for the user.
    """
    chat_id: str
    user_id: str

class ChatSession(BaseModel):
    """
    ChatSession model representing a chat session.

    Attributes:
        user_id (str): The unique identifier for the user.
    """
    user_id: str
