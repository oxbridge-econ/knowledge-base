"""Module for retrievers that fetch documents from various sources."""
from venv import logger
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import VectorStoreRetriever
from models.chroma import vectorstore

class DocRetriever(BaseRetriever):
    """
    DocRetriever is a class that retrieves documents using a VectorStoreRetriever.
    Attributes:
        retriever (VectorStoreRetriever): An instance used to retrieve documents.
        k (int): The number of documents to retrieve. Default is 10.
    Methods:
        __init__(k: int = 10) -> None:
            Initializes the DocRetriever with a specified number of documents to retrieve.
        _get_relevant_documents(query: str, *, run_manager) -> list:
            Retrieves relevant documents based on the given query.
            Args:
                query (str): The query string to search for relevant documents.
                run_manager: An object to manage the run (not used in the method).
            Returns:
                list: A list of Document objects with relevant metadata.
    """
    retriever: VectorStoreRetriever = None
    k: int = 10

    def __init__(self, req, k: int = 10) -> None:
        super().__init__()
        # _filter={}
        # if req.site != []:
        #     _filter.update({"site": {"$in": req.site}})
        # if req.id != []:
        #     _filter.update({"id": {"$in": req.id}})
        self.retriever = vectorstore.as_retriever(
            search_type='similarity',
            search_kwargs={
                "k": k,
                # "filter": _filter,
                # "score_threshold": .1
            }
        )

    def _get_relevant_documents(self, query: str, *, run_manager) -> list:
        try:
            retrieved_docs = self.retriever.invoke(query)
            # doc_lst = []
            for doc in retrieved_docs:
                doc.metadata['id'] = doc.id
                # date = str(doc.metadata['publishDate'])
                doc.metadata['content'] = doc.page_content
                # doc_lst.append(Document(
                #     page_content = doc.page_content,
                #     metadata = doc.metadata
                #     # metadata = {
                #     #     "content": doc.page_content,
                #     #     # "id": doc.metadata['id'],
                #     #     "title": doc.metadata['subject'],
                #     #     # "site": doc.metadata['site'],
                #     #     # "link": doc.metadata['link'],
                #     #     # "publishDate": doc.metadata['publishDate'].strftime('%Y-%m-%d'),
                #     #     # 'web': False,
                #     #     # "source": "Finfast"
                #     # }
                # ))
            # print(doc_lst)
            return retrieved_docs
        except RuntimeError as e:
            logger.error("Error retrieving documents: %s", e)
            return []
