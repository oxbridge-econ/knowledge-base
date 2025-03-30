# """Module for the Vector Database."""
# from langchain_chroma import Chroma
# from models.llm import EmbeddingsModel

# vectorstore = Chroma(
#     embedding_function=EmbeddingsModel("all-MiniLM-L6-v2"),
#     collection_name="email",
#     persist_directory="models/chroma/data"
# )

# # def create_or_get_collection(collection_name: str):
# #     """
# #     Creates a new collection or gets an existing collection from the Vector Database.

# #     Args:
# #         collection_name (str): The name of the collection.

# #     Returns:
# #         chromadb.Collection: The collection associated with the provided name.
# #     """
# #     chroma_client = chromadb.PersistentClient(path="models/chroma/data")
# #     collection = chroma_client.get_or_create_collection(collection_name)
# #     # try:
# #     #     collection = chroma_client.create_collection(collection_name)
# #     # except chromadb.errors.UniqueConstraintError:
# #     #     collection = chroma_client.get_collection(collection_name)
# #     return collection
