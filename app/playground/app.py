"""Streamlit app example."""
import logging
import uuid
import streamlit as st

from chain import RAGChain
from retriever import DocRetriever
from controllers import mail

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.ERROR)

with st.sidebar:
    st.header("Controls")
    if st.button("Collect Data"):
        result = mail.collect()
        with st.chat_message("assistant"):
            response_content = st.markdown(result)

if 'chat_id' not in st.session_state:
    st.session_state.chat_id = str(uuid.uuid4())
    st.session_state.user_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What is up?"):

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    req = {"query": prompt}
    chain = RAGChain(DocRetriever(req=req))

    result = chain.invoke({"input": req['query']},
                    config={"configurable": {"session_id": st.session_state.chat_id}})
    with st.chat_message("assistant"):
        response_content = st.markdown(result['answer'])
    st.session_state.messages.append({"role": "assistant", "content": result['answer']})
