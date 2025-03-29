"""Module containing utility functions for the chatbot application."""
import json
from chain import RAGChain, FollowUpChain
from schema import ReqData
from retriever import DocRetriever

followUpChain = FollowUpChain()

async def generate(req: ReqData):
    """
    Asynchronously generates responses based on the provided request data.

    This function uses different processing chains depending on the `web` attribute of the request.
    It streams chunks of data and yields server-sent events (SSE) for answers and contexts.
    Additionally, it generates follow-up questions and updates citations.

    Args:
        req (ReqData): Request data containing user and chat info, query, and other parameters.

    Yields:
        str: Server-sent events (SSE) for answers, contexts, and follow-up questions in JSON format.
    """
    chain = RAGChain(DocRetriever(req=req))
    session_id = "/".join([req.user_id, req.chat_id])
    contexts = []
    for chunk in chain.stream({"input": req.query},
                                   config={"configurable": {"session_id": session_id}}):
        if 'answer' in chunk:
            yield "event: answer\n"
            yield f"data: {json.dumps(chunk)}\n\n"
        elif 'context' in chunk:
            for context in chunk['context']:
                yield "event: context\n"
                yield f"data: {json.dumps({'context': context.metadata})}\n\n"
    yield "event: questions\n"
    yield f"data: {json.dumps({'questions': followUpChain.invoke(req.query, contexts)})}\n\n"