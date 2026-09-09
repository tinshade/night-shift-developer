import os
import asyncio
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain.agents import create_agent


load_dotenv()

async def main(query:str):
    model = init_chat_model(
        model = os.environ.get('GROQ_FREE_MODEL'),
        model_provider="groq",
        temperature = 0.2,
        api_key=os.environ.get('GROQ_API_KEY')
    )
    
    client_config:dict = {
        "github": {
            "transport": "stdio",
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-github",
            ],
            "env": {
                "GITHUB_PERSONAL_ACCESS_TOKEN":
                    os.environ.get(
                        "GITHUB_PERSONAL_ACCESS_TOKEN"
                    )
            },
        }
    }
    
    client = MultiServerMCPClient(client_config)
    
    async with client.session(server_name="github") as session:
        # Convert MCP tools to LangChain compatible tools
        tools = await load_mcp_tools(session)
        
        # Create a ReAct agent with LangGraph
        agent = create_agent(model=model, tools=tools)
        
        response = await agent.ainvoke({
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ]
        })
        print("\nAgent Responses")
        print(response["messages"][-1].content)
    

if __name__ == "__main__":
    templates = [
        "Output the first like from `README.md` file. Following are the repository details. Owner: tinshade. Repository Name: night-shift-developer. Branch: dev"
    ]
    query = str(input())
    asyncio.run(main(query))