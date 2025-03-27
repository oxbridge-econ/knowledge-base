"""Module to run the mail collection process."""
from dotenv import load_dotenv

# from controllers import mail
from chain import RAGChain
from retriever import DocRetriever

load_dotenv()

if __name__ == "__main__":
    # mail.collect()
    # mail.get_documents()
    req = {
        "query": "Just give me an update?",
    }
    chain = RAGChain(DocRetriever(req=req))
    result = chain.invoke({"input": req['query']},
                       config={"configurable": {"session_id": "20250301"}})
    print(result)
    print(result.get("answer"))
