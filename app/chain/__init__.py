"""Module containing functions to create conversational chains for conversational AI."""
import os
import json
from datetime import datetime
from venv import logger

from pymongo import errors
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import BaseMessage, message_to_dict
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains.retrieval import create_retrieval_chain
from langchain.prompts.chat import ChatPromptTemplate, MessagesPlaceholder
from langchain_mongodb import MongoDBChatMessageHistory

from schema import FollowUpQ
from models.llm import GPTModel

llm = GPTModel()

SYS_PROMPT = """
You are a financial expert with deep knowledge in economics and finance. Your role is to provide well-supported, credible answers to user questions by referencing the following contexts:

{context}

Use your expertise to enhance responses, but ensure all information is consistent with the provided context.

Please adhere to these guidelines:

### Answering Instructions:

1. **Concise Introduction**: Begin each answer with a clear, concise summary or introductory paragraph. Do not start with bullet points; instead, offer an overview of the main insights before detailing specifics.

2. **Logical Organization**: Structure your answer logically, especially when using bullet points:
    - Briefly describe the event, policy, or situation (who, when, where, why).
    - Analyze market reactions or responses, using data, quotes, or examples from authoritative sources.
    - Conclude with expected impacts or future implications, supported by reasoning, historical context, or theory.

3. **Context Usage**:
    - Treat each context as a separate chunk and cite it at the end of each relevant sentence using **[citation:x]**, where *x* is the chunk index.
    - Avoid unnecessary citations or placing citations only at the end of the response.
    - Do not speculate or infer information if no relevant context is available.
    - Supplement with your own knowledge only when it aligns with the context. Exclude unrelated information.

4. **Timeliness**:
    - If the user does not specify a timeframe, prioritize the most recent and relevant information.
    - Always include dates when mentioning events, statistics, plans, or policies. Interpret references like “this year” based on the source's publication date.

5. **Formatting**:
    - Format answers in **Markdown** for clarity and readability.
    - Use bullet points where appropriate, ensuring logical flow and cohesion.

6. **Authoritative References**:
    - Use direct quotes for official sources, e.g., *“According to the Central Government...”*.
    - For public opinion or general perspectives, use phrases like *“According to public opinion...”* or *“As noted by various commentators...”*.

7. **Relevance**:
    - Respond strictly based on the provided contexts and instructions.
    - Do not provide information or perform actions outside the scope of the query.
    - If no useful information is found in the knowledge base or contexts, state this clearly without speculation.

By following these instructions, your answers will be thorough, logically structured, and highly credible, reflecting professional expertise in economic and financial topics.

Sample Answer Template:

Introduction

Brief Overview: [Concise statement about the current state or topic.]
Key Events: [Specific incidents or milestones.]
Concrete Details: [Factual data or specific information.]
Context: [Broader implications or consequences, if relevant.]

### Section 1: [Section Title]

[First point related to this section.]
[Second point related to this section.]
[Additional points as needed.]

### Section 2: [Section Title]

[First point related to this section.]
[Second point related to this section.]
[Additional points as needed.]

[Add more sections as necessary.]
"""


PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYS_PROMPT),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ]
)

docs_chain = create_stuff_documents_chain(llm, PROMPT)

class MessageHistory(MongoDBChatMessageHistory):
    """
    A class to handle the history of chat messages stored in MongoDB.

    Methods
    -------
    add_message(message: BaseMessage) -> None
        Appends the given message to the MongoDB collection with a timestamp.
    """
    def add_message(self, message: BaseMessage) -> None:
        """Append the message to the record in MongoDB"""
        try:
            self.collection.insert_one(
                {
                    self.session_id_key: self.session_id,
                    self.history_key: json.dumps(message_to_dict(message)),
                    "CreatedDate": datetime.now()
                }
            )
        except errors.WriteError as err:
            logger.error(err)

def get_message_history(
        session_id: str,
        mongo_url = os.environ.get("CHATHISTORY_MONGODB_URL")) -> MessageHistory:
    """
    Creates a MongoDBChatMessageHistory instance for a given session.

    Args:
        session_id (str): The unique identifier for the chat session.
        mongo_url (str): The MongoDB connection string.

    Returns:
        MongoDBChatMessageHistory: An instance of MongoDBChatMessageHistory
        configured with session ID and connection string.
    """
    return MessageHistory(
        session_id = session_id,
        connection_string=str(mongo_url), database_name='mailbox')

class RAGChain(RunnableWithMessageHistory):
    """
    RAGChain is a class that extends RunnableWithMessageHistory to create a RAG chain.

    Attributes:
        retriever: An instance responsible for retrieving relevant documents or information.

    Methods:
        __init__(retriever):
            Initializes the RAGChain with a retriever and sets up retrieval chain, message history,
            and keys for input, history, and output messages.
    """
    def __init__(self, retriever):
        super().__init__(
            create_retrieval_chain(retriever, docs_chain),
            get_message_history,
            input_messages_key="input",
            history_messages_key="chat_history",
            output_messages_key="answer"
        )

class FollowUpChain():
    """
    FollowUpQChain is a class to generate follow-up questions based on contexts and initial query.

    Attributes:
        parser (PydanticOutputParser): An instance of PydanticOutputParser to parse the output.
        chain (Chain): A chain of prompts and models to generate follow-up questions.

    Methods:
        __init__():
            Initializes the FollowUpQChain with a parser and a prompt chain.
        
        invoke(contexts, query):
            Invokes the chain with the provided contexts and query to generate follow-up questions.

                contexts (str): The contexts to be used for generating follow-up questions.
                query (str): The initial query to be used for generating follow-up questions.
    """
    def __init__(self):
        self.parser = PydanticOutputParser(pydantic_object=FollowUpQ)
        prompt = ChatPromptTemplate.from_messages([
                    ("system", "You are a professional commentator on current events.Your task\
                      is to provide 3 follow-up questions based on contexts and initial query."),
                    ("system", "contexts: {contexts}"),
                    ("system", "initial query: {query}"),
                    ("human", "Format instructions: {format_instructions}"),
                    ("placeholder", "{agent_scratchpad}"),
                ])
        self.chain = prompt | llm | self.parser

    def invoke(self, query, contexts):
        """
        Invokes the chain with the provided content and additional parameters.

        Args:
            content (str): The article content to be processed.

        Returns:
            The result of the chain invocation.
        """
        result = self.chain.invoke({
            'contexts': contexts,
            'format_instructions': self.parser.get_format_instructions(),
            'query': query
        })
        return result.questions
