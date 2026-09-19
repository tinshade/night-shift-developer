class TokenBudgeting:
    
    def __init__(self, max_tokens_per_request:int = 4000):
        self.max_tokens_per_request:int = max_tokens_per_request
        self.usage:dict[str, int] = {
            "total_input": 0,
            "total_output": 0,
            "requests": 0,
        }
    
    def estimate_tokens(self, text:str) -> int:
        """Rough token estimation (actual would use tiktoken)""" # https://github.com/openai/tiktoken
        return int(len(text.split()) * 1.3)
    
    # Runs before the LLM call
    def check_budget(self, text:str) -> tuple[bool, int]:
        """Check if request is within budget"""
        tokens:int = self.estimate_tokens(text=text)
        return tokens<=self.max_tokens_per_request, tokens
    
    def record_usage(self, input_tokens:int, output_tokens:int) -> None:
        """Record token usage"""
        self.usage["total_input"] += input_tokens
        self.usage["total_output"] += output_tokens
        self.usage["requests"] += 1
        
    def get_stats(self) -> dict[str,int]:
        return self.usage

if __name__ == "__main__":
    tb = TokenBudgeting(max_tokens_per_request=5000)