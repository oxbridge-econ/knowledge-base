"""Module for OpenAI model and embeddings."""
import os
import onnxruntime as ort
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_huggingface import HuggingFacePipeline
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from huggingface_hub import hf_hub_download

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

class Phi4MiniONNXLLM:
    """
    A class for interfacing with a pre-trained ONNX model for inference.

    Attributes:
        session (onnxruntime.InferenceSession): The ONNX runtime inference session for the model.
        input_name (str): The name of the input node in the ONNX model.
        output_name (str): The name of the output node in the ONNX model.

    Methods:
        __init__(model_path):
            Initializes the Phi4MiniONNXLLM instance by loading the ONNX model from specified path.
        
        __call__(input_ids):
            Performs inference on the given input data and returns the model's output.
    """
    def __init__(self, repo_id, subfolder, onnx_file="model.onnx", weights_file="model.onnx.data"):
        self.repo_id = repo_id
        model_path = hf_hub_download(repo_id=repo_id, filename=f"{subfolder}/{onnx_file}")
        weights_path = hf_hub_download(repo_id=repo_id, filename=f"{subfolder}/{weights_file}")
        self.session = ort.InferenceSession(model_path)
        # Verify both files exist
        print(f"Model path: {model_path}, Exists: {os.path.exists(model_path)}")
        print(f"Weights path: {weights_path}, Exists: {os.path.exists(weights_path)}")
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def __call__(self, input_text):
        # Assuming input_ids is a tensor or numpy array
        tokenizer = AutoTokenizer.from_pretrained("microsoft/Phi-4-mini-instruct-onnx")
        inputs = tokenizer(input_text, return_tensors="pt")
        input_feed = {
            self.input_name: inputs["input_ids"].numpy(),
            "attention_mask": inputs["attention_mask"].numpy(),
            # Add past_key_values if applicable
        }
        outputs = self.session.run([self.output_name], input_feed)
        return outputs

class HuggingfaceModel(HuggingFacePipeline):
    """
    HuggingfaceModel is a wrapper class for the Hugging Face text-generation pipeline.

    Attributes:
        name (str): The name or path of the pre-trained model to load from Hugging Face.
        max_tokens (int): The maximum number of new tokens to generate in the text output.
        Defaults to 200.

    Methods:
        __init__(name, max_tokens=200):
            Initializes the HuggingfaceModel with the specified model name and maximum token limit.
    """
    def __init__(self, name, max_tokens=500):
        super().__init__(pipeline=pipeline(
            "text-generation",
            model=AutoModelForCausalLM.from_pretrained(name),
            tokenizer=AutoTokenizer.from_pretrained(name),
            max_new_tokens=max_tokens
            )
        )

# model_name = "microsoft/phi-1_5"
# tokenizer = AutoTokenizer.from_pretrained(model_name)
# model = AutoModelForCausalLM.from_pretrained(model_name)
# pipe = pipeline("text-generation", model=model, tokenizer=tokenizer, max_new_tokens=200)

# phi4_llm = HuggingFacePipeline(pipeline=pipe)

# tokenizer = AutoTokenizer.from_pretrained("openai-community/gpt2", pad_token_id=50256)
# model = AutoModelForCausalLM.from_pretrained("openai-community/gpt2")
# pipe = pipeline(
#     "text-generation", model=model, tokenizer=tokenizer,
#       max_new_tokens=10, truncation=True,  # Truncate input sequences
# )
# phi4_llm = HuggingFacePipeline(pipeline=pipe)
