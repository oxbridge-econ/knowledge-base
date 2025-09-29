"""Module for OpenAI model and embeddings."""
from openai import AzureOpenAI
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from dotenv import load_dotenv
load_dotenv()


class GPTModel(AzureChatOpenAI):
    """
    GPTModel class that extends AzureChatOpenAI.

    This class initializes a GPT model with specific deployment settings and a callback function.

    Attributes:
        callback (function): The callback function to be used with the model.

    Methods:
        __init__(callback):
            Initializes the GPTModel with the specified callback function.
    """
    def __init__(self):
        super().__init__(
        deployment_name="gpt-4o",
        streaming=True, temperature=0)

class GPTEmbeddings(AzureOpenAIEmbeddings):
    """
    GPTEmbeddings class that extends AzureOpenAIEmbeddings.

    This class is designed to handle embeddings using GPT model provided by Azure OpenAI services.

    Attributes:
        Inherits all attributes from AzureOpenAIEmbeddings.

    Methods:
        Inherits all methods from AzureOpenAIEmbeddings.
    """

client = AzureOpenAI()
