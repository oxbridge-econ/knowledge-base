"""Module containing the data models for the application."""
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from pydantic import BaseModel, Field

task_states: Dict[str, str] = {}

class EmailFilter(BaseModel):
    """
    EmailQuery model representing the structure of an email query.

    Attributes:
        subject (Optional[str]): The subject of the email to search for.
        from_email (Optional[str]): The sender's email address.
        to_email (Optional[str]): The recipient's email address.
        cc_email (Optional[str]): The CC email address.
        has_words (Optional[str]): Words that the email must contain.
        not_has_words (Optional[str]): Words that the email must not contain.
        size (Optional[int]): The size of the email in bytes.
        date_within (Optional[str]): The date within which to search for emails.
        after (Optional[str]): The date after which to search for emails.
        max_results (Optional[int]): The maximum number of results to return.
    """
    id: Optional[str] = None
    subject: Optional[str] = None
    from_email: Optional[str] = Field(None, alias="from")
    to_email: Optional[str] = Field(None, alias="to")
    cc_email: Optional[str] = Field(None, alias="cc")
    has_words: Optional[str] = None
    not_has_words: Optional[str] = None
    # size: Optional[int] = None
    before: Optional[str] = None
    after: Optional[str] = None
    max_results: Optional[int] = Field(10, alias="maxResults")
    topic_detect: Optional[bool] = False
    topics: Optional[List[str]] = ["Finance", "Economy", "AI", "IT", "Politics"]

    @classmethod
    def validate_before_after(
        cls, before: Optional[str], after: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """
        Validates and adjusts the 'before' and 'after' date parameters.

        This method ensures that the 'before' date is greater than the 'after' date.
        If 'before' is not provided, it defaults to six months prior to the current date.

        Args:
            before (Optional[str]): The 'before' date in the format "YYYY/MM/DD". Defaults to None.
            after (Optional[str]): The 'after' date in the format "YYYY/MM/DD". Defaults to None.

        Returns:
            tuple[Optional[str], Optional[str]]: 
            A tuple containing the validated 'before' and 'after' dates.

        Raises:
            ValueError: If the 'before' date is not greater than the 'after' date.
        """
        # if after is None:
        #     after = (datetime.now() - timedelta(days=6 * 30)).strftime("%Y/%m/%d")
        if before and after:
            before_dt = datetime.strptime(before, "%Y/%m/%d")
            after_dt = datetime.strptime(after, "%Y/%m/%d")
            if before_dt <= after_dt:
                raise ValueError("The 'before' date must be greater than the 'after' date.")
        return before, after

    def __init__(self, **data):
        super().__init__(**data)
        self.before, self.after = self.validate_before_after(self.before, self.after)
    max_results: Optional[int] = 10

class EmailQuery(BaseModel):
    """
    EmailQuery represents a query for emails with optional filtering.

    Attributes:
        id (str): A unique identifier for the query, generated using UUIDv5 of current timestamp.
        name (str, optional): An optional name for the query.
        filter (EmailFilter, optional): An optional filter to apply to the email query.
    """
    id: str = str(uuid.uuid5(uuid.NAMESPACE_DNS, datetime.now().isoformat()))
    name: str = None
    filter: EmailFilter = None

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

class MailReqData(BaseModel):
    """
    MailReqData is a data model representing the structure of a mail request.

    Attributes:
        query (str): The query or message content sent by the user.
    """
    email: str
    query: Optional[EmailQuery] = None

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

class DocsReq(BaseModel):
    """
    Request schema for document retrieval operations.

    Attributes:
        limit (Optional[int]): Maximum number of results to return.
            Defaults to 10.
        skip (Optional[int]): Number of results to skip for pagination.
            Defaults to 0.
    """
    limit: Optional[int] = 10
    skip: Optional[int] = 0
