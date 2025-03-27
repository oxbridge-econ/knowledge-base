from langchain_huggingface import HuggingFacePipeline

# Define the model ID
model_id = "gpt2"
model_id = "microsoft/Phi-4-mini-instruct"
model_id = "Qwen/Qwen2.5-7B-Instruct"
model_id = "microsoft/Phi-3-small-8k-instruct"

# Create a pipeline for text generation
llm = HuggingFacePipeline.from_model_id(
    model_id=model_id,
    task="text-generation",
    device=-1,
    # trust_remote_code=True,
    pipeline_kwargs={
        "max_new_tokens": 256,
        "top_k": 50
    },
)

# Use the model to generate text
response = llm.invoke("Hello, how are you?")
print(response)