import os
from dotenv import load_dotenv
from token_limiter import TokenBudgeting

from langsmith import traceable

from langchain.chat_models import init_chat_model

load_dotenv()

class LambLLM:
    """Experimental LLM for testing Budegeting and MCP tool-calling"""
    
    def __init__(self, max_tokens:int = 1000):
        self.max_tokens:int = max_tokens
        self.llm = init_chat_model(
            model = os.environ.get('GROQ_FREE_MODEL'),
            model_provider="groq",
            temperature = 0.2,
            api_key=os.environ.get('GROQ_API_KEY')
        )
        self.budget = TokenBudgeting(max_tokens_per_request=self.max_tokens)
        
    @traceable(name="budgeted_invoke", run_type="llm")
    def invoke(self, query:str) -> str:
        # Check budget
        within_budget, tokens = self.budget.check_budget(text=query)
        if not within_budget:
            raise ValueError(f"Query exceeds token budget: {tokens} > {self.budget.max_tokens_per_request}")
        
        # Execute
        response = self.llm.invoke(query)
        result = response.content
        
        # Record usage
        output_tokens = self.budget.estimate_tokens(result)
        self.budget.record_usage(input_tokens=tokens, output_tokens=output_tokens)
        
        return result
    
    def get_status(self) -> dict:
        return self.budget.get_stats()
        


if __name__ == "__main__":
    lamb = LambLLM(max_tokens=1)
    try:
        lamb.invoke(query="What can I use LangSmith for?")
    except Exception as e:
        print(str(e))