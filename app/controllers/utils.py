"""Module for utility functions related to MongoDB operations."""
from models.db import MongodbClient

collection = MongodbClient["tasks"]["tasks"]

def upsert_task(_id, task):
    """
    Update or add an item in the 'tasks' list based on the 'id' field.

    Args:
        _id: The _id of the document to update
        task: Dictionary with 'id' and 'value' (e.g., {"id": 1, "value": "new_value"})
    """
    result = collection.update_one(
        {
            "_id": _id,
            "tasks.id": task["id"]
        },
        {
            "$set": { "tasks.$.status": task["status"] }
        },
        upsert=False
    )
    if result.matched_count == 0:
        result = collection.update_one(
            { "_id": _id },
            {
                "$push": { "tasks": { "$each": [task], "$slice": -10 } }
            },
            upsert=True
        )
