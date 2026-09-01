import os
from dotenv import load_dotenv

load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import json



class ChatExample:
    
    def __init__(self):
        self.model = ChatGroq(
            api_key=os.environ.get('GROQ_LLM_KEY'),
            model_name = os.environ.get('GROQ_FREE_MODEL'),
            temperature = 0.7
        )

        self.parser = JsonOutputParser(pydantic_object = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "price": {"type": "number"},
                "features": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        })
    
    
    def create_prompt(self):
        # Create a simple prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Extract product details into JSON with this structure:
                {{
                    "name": "product name here",
                    "price": number_here_without_currency_symbol,
                    "features": ["feature1", "feature2", "feature3"]
                }}"""),
            ("user", "{input}")
        ])
        
        return prompt
    
    def main(self):

        # Create the chain that guarantees JSON output
        chain = self.create_prompt() | self.model | self.parser

        def parse_product(description: str) -> dict:
            result = chain.invoke({"input": description})
            print(json.dumps(result, indent=2))

                
        # Example usage
        description = """The Kees Van Der Westen Speedster is a high-end, single-group espresso machine known for its precision, performance, 
        and industrial design. Handcrafted in the Netherlands, it features dual boilers for brewing and steaming, PID temperature control for 
        consistency, and a unique pre-infusion system to enhance flavor extraction. Designed for enthusiasts and professionals, it offers 
        customizable aesthetics, exceptional thermal stability, and intuitive operation via a lever system. The pricing is approximatelyt $14,499 
        depending on the retailer and customization options."""

        parse_product(description)
        

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore

class EmbeddingExample:
    def __init__(self):
        # 1. Create the embedding model (using a free Hugging Face sentence-transformer)
        self.embedding = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    
    def initialize_vector_store(self, embedding):
        vector_store = InMemoryVectorStore(embedding=embedding)
        vector_store.add_texts([
            "LangChain is a framework for building context-aware applications.",
            "Groq provides ultra-fast LLM inference via LPU."
        ])
        return vector_store
    
    def run_similarity_search(self, vector_store:InMemoryVectorStore, query:str):
        results = vector_store.similarity_search(query=query)
        return results
    
    def main(self):
        # 2. Embed text and store in a vector store
        vector_store = self.initialize_vector_store(embedding=self.embedding)
        
        # 3. Perform a similarity search query
        results = self.run_similarity_search(vector_store=vector_store, query="What is Groq?")
        print(results, results[0].page_content)
        
        # 4. Initialize Groq for text generation/chat responses
        llm = ChatGroq(model=os.environ.get('GROQ_FREE_MODEL'), api_key=os.environ.get('GROQ_LLM_KEY'))
        response = llm.invoke("Summarize what Groq is based on: " + results[0].page_content)
        print(response.content)



if __name__ == "__main__":
    
    EmbeddingExample().main()