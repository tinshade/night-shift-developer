import os
from dotenv import load_dotenv
import tempfile

from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from langchain.chat_models import init_chat_model
from langchain_huggingface import HuggingFaceEmbeddings


load_dotenv()
EMBEDDINGS_MODEL = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
# Sample knowledge base
KNOWLEDGE_BASE = """# LangChain Framework

LangChain is a framework for developing applications powered by language models. It was created by Harrison Chase in October 2022.

## Core Components

1. **Models**: LangChain supports various LLM providers including OpenAI, Anthropic, and local models.

2. **Prompts**: Templates for structuring inputs to language models.

3. **Chains**: Sequences of calls to models and other components.

4. **Agents**: Systems that use LLMs to determine which actions to take.

5. **Memory**: Components for persisting state between chain/agent calls.

## LangGraph

LangGraph is a library for building stateful, multi-actor applications. Key features:
- State management
- Cycles and loops
- Human-in-the-loop
- Persistence

## Pricing

LangChain itself is open source and free. LangSmith (the observability platform) has a free tier and paid plans starting at $39/month.

## Getting Started

Install with: pip install langchain langchain-openai
Create your first chain in under 10 lines of code.
"""

def create_knowledgebase():
    """Create a vector store from knowledge base."""
    
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    doc = Document(page_content=KNOWLEDGE_BASE, metadata = {"source": "langchain_knowledge_base.md"})
    
    chunks = splitter.split_documents([doc])
    
    
    # Create vector store
    
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=EMBEDDINGS_MODEL,
        persist_directory=tempfile.mkdtemp()
    )
    
    return vector_store

def demo_basic_rag():
    
    vector_store = create_knowledgebase()
    retriever = vector_store.as_retriever(search_type="similarity", search_kwards={})
    llm = init_chat_model(
        model = os.environ.get('GROQ_FREE_MODEL'),
        model_provider="groq",
        temperature = 0.2,
        api_key=os.environ.get('GROQ_API_KEY')
    )
    
    # RAG Prompt Template
    prompt = ChatPromptTemplate.from_template(
        template = """
        Answer the question based only on the following context:
        {context}
        Question: {question}
        Answer: 
        
        Make sure you answer in a concise manner, and if you don't know, just say "I don't know".
        """
    )
    
    def format_docs(docs):
        return "\n\n".join([doc.page_content for doc in docs])
    
    rag_chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    
    # Test RAG
    
    questions = [
        "What is Langchain?",
        "Who created Langchain?",
        "What is LangGraph used for?"
    ]
    
    print("Basic RAG Demo:\n")
    for q in questions:
        answer = rag_chain.invoke(q)
        print(f"Q: {q}")
        print(f"A: {answer}\n")
        


if __name__ == "__main__":
    demo_basic_rag()