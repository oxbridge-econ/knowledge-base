"""Module for utility functions related to MongoDB operations."""
import time
from venv import logger
from datetime import datetime
from langchain_core.documents import Document
from openai import RateLimitError

from models.db import MongodbClient
from controllers.topic import detector

def check_relevance(documents: Document, topics: list[str]) -> list[Document]:
    """
    Checks the relevance of documents list using a detector and returns the relevant documents.

    For each document, the detector is invoked to check its relevance.
    If the verdict is positive, the document is considered relevant and added to the list.
    If a RateLimitError occurs, the method retries up to a maximum number of times,
    waiting between retries. If the maximum retries are reached or other exceptions
    (ValueError, TypeError, KeyError) occur, the document is added to the result list.

    Args:
        documents (list[Document]): A list of Document objects to check for relevance.

    Returns:
        list[Document]:
            A list of Document objects deemed relevant or added as fallback due to errors.
    """
    rel_documents = []
    max_retries = 3
    for document in documents:
        for retry in range(max_retries):
            try:
                is_relevant = detector.invoke(
                    {"document": document, "topics": topics}).model_dump()['verdict']
                if is_relevant:
                    logger.info("Document %s is relevant to the topic.",
                                document.metadata["id"])
                    rel_documents.append(document)
                else:
                    logger.info("Document %s is not relevant to the topic.",
                                document.metadata["id"])
                break  # Success, exit retry loop
            except RateLimitError:
                wait_time = 60
                logger.warning("Rate limit hit. Waiting %ds before retry %d/%d",
                                wait_time, retry+1, max_retries)
                if retry < max_retries - 1:
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries reached for OpenAI API. Skipping document.")
                    # Just add the document without checking relevance as fallback
                    rel_documents.append(document)
            except (ValueError, TypeError, KeyError) as e:
                logger.error("Error checking document relevance: %s", str(e))
                # Add document anyway as fallback
                rel_documents.append(document)
                break
    return rel_documents


def upsert(
    _id,
    element,
    *,
    collection=None,
    db="task",
    size: int = 100,
    field="tasks"
):
    """
    Inserts or updates an element within a specified collection and field in a MongoDB database.

    If an element with the same 'id' exists in the specified field array,
    updates its fields (except 'id').
    If not, appends the element to the array, maintaining a maximum size.

    Args:
        _id: The unique identifier of the parent document.
        element (dict): The element to insert or update. Must contain an 'id' key.
        collection (Optional[Collection]): The MongoDB collection to operate on.
            If None, uses MongodbClient[db][element["type"]].
        db (str, optional): The database name to use if collection is None. Defaults to "task".
        size (int, optional):
            The maximum number of elements to keep in the field array. Defaults to 10.
        field (str, optional):
            The name of the array field to update within the document. Defaults to "tasks".

    Returns:
        None

    Side Effects:
        Modifies the specified MongoDB document by updating or appending the element.
        Sets 'createdTime' and 'updatedTime' fields on the element as appropriate.
    """
    if collection is None:
        collection = MongodbClient[db][element["type"]]
    current_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    if "createdTime" not in element:
        element["createdTime"] = current_time
    element["updatedTime"] = current_time
    update_fields = {f"{field}.$.{k}": v for k, v in element.items() if k != "id"}
    result = collection.update_one(
        {
            "_id": _id,
            f"{field}.id": element["id"]
        },
        {
            "$set": update_fields
        },
        upsert=False
    )
    if result.matched_count == 0:
        result = collection.update_one(
            { "_id": _id },
            {
                "$push": { f"{field}": { "$each": [element], "$slice": -size } }
            },
            upsert=True
        )
