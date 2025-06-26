"""Module for utility functions related to MongoDB operations."""
from datetime import datetime
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
