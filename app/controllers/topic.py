"""Module for topic detection."""
from langchain.output_parsers import PydanticOutputParser
from langchain.prompts import PromptTemplate
from pydantic import BaseModel, Field

from models.llm import GPTModel

class Result(BaseModel):
    """
    Represents the result of evaluating whether an email is related to specific topics.

    Attributes:
        verdict (bool): True if the email is related to the topics, False otherwise.
    """
    verdict: bool = Field(
        description="True if the email is related to the topics, False otherwise."
    )

parser = PydanticOutputParser(pydantic_object=Result)

prompt = PromptTemplate(
    template="""
    You are a professional email labeling assistant. Your task is check if the email content is related to the following topics: {topics}.

    Email Content:
    {document}

    Return results in strict JSON format matching this schema:
    {format_instructions}
    """,
        input_variables=["document", "topics"],
        partial_variables={
            "format_instructions": parser.get_format_instructions()
        },
    )

detector = prompt | GPTModel() | parser
