"""Module for utility functions related to MongoDB operations."""
from models.db import MongodbClient

def upsert(
    _id,
    element,
    *,
    collection=None,
    db="task",
    size: int = 10,
    field="tasks"
):
    """
    Inserts or updates an element in a nested array field of a MongoDB document.

    If an element with the same 'id' exists in the array field, it updates the element's fields.
    If not, it appends the new element to the array, maintaining a maximum array size.

    Args:
        _id: The unique identifier of the MongoDB document.
        element (dict): The element to insert or update. Must contain an 'id' key.
        db (str, optional): The database name. Defaults to "tasks".
        service (str, optional): The collection name within the database. Defaults to "gmail".
        size (int, optional): The maximum size of elements in the array field. Defaults to 10.
        field (str, optional): The name of the array field within the document. Defaults to "tasks".

    Returns:
        None
    """
    if collection is None:
        collection = MongodbClient[db][element["type"]]
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
