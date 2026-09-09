import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_experimental.text_splitter import SemanticChunker
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from dotenv import load_dotenv



load_dotenv()

EMBEDDINGS_MODEL = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


# Sample documents
SAMPLE_DOCUMENTS = """
# Authentication Guide

## OAuth2 Authentication
To authenticate with our API, you need OAuth2 credentials.
Frist, obtain a client_id and client_secret from the developer portal.
Make a POST request to /oauth/token with grant_type=client_credentials.
The response contains an access_token valid for 3600 seconds.
Icnlude this token in the Authorization header as 'Bearer <token>'.

## Rate Limiting
Our API implements rate limiting using a token bucket algorithm.
Free tier: 100 requests per minute.
Pro tier: 1000 requests per minute.
Enterprise tier: Custom limits.
When rate limited, you receive a 429 status code.
The Retry-After header indicates when to retry.

## Error Handling
All errors return a standard JSON format.
The 'code' field contains a machine-readable error code.
The 'message' field contains a human-readable description.
Common errors: AUTH_FAILED, RATE_LIMITED, INVALID_REQUEST.
Always check the HTTP status code first, then parse the error body.

## Webhooks
Configure webhooks in your dashboard settings.
We support HTTP and HTTPS endpoints.
Webhook payloads are signed with HMAC-SHA256.
Verify signatures using your webhook secret.
Failed deliveries are retried with exponential backoff.
"""
sample_document = Document(page_content=SAMPLE_DOCUMENTS, metadata = {"source": "SecurityPractices.md"})

def get_rts_chunks(doc:Document):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents([doc])
    return chunks

def get_sem_chunks(doc:Document):
    chunker = SemanticChunker(
        embeddings=EMBEDDINGS_MODEL,
        breakpoint_threshold_type='percentile',
        breakpoint_threshold_amount=90
    )
    
    chunks = chunker.split_documents([doc])
    return chunks


def _recursive_fallback(query:Document, fallback_chunk_size:int=500):
    splitter = RecursiveCharacterTextSplitter(chunk_size=fallback_chunk_size, chunk_overlap=50)
    chunks = splitter.split_documents([query])
    
    return chunks

def smart_chunker(query:Document, use_sematic:bool=True, fallback_chunk_size:int = 500):
    """
    Production chunking with semantic as primary, recursive as fallback.
    """
    try:
        if use_sematic:
            chunker = SemanticChunker(
                embeddings=EMBEDDINGS_MODEL,
                breakpoint_threshold_type='percentile',
                breakpoint_threshold_amount=90
            )
            chunks = chunker.split_documents([query])
            # Validate that the chunks are not too large
            max_chunk_size = 2000
            if any(len(c.page_content) > max_chunk_size for c in chunks):
                return _recursive_fallback(query, fallback_chunk_size)
            return chunks
    
    except Exception as e:
        print(f'Semantic chunking failed: {e}, using fallback')
        return _recursive_fallback(query, fallback_chunk_size)
    
    return _recursive_fallback(query, fallback_chunk_size)
    

# Using smart_chunker
#chunks = smart_chunker(query=sample_document)
smart_vs = Chroma.from_documents(
    documents=smart_chunker(query=sample_document),
    embedding=EMBEDDINGS_MODEL,
    collection_name="smart_collection"
)


rts_vs = Chroma.from_documents(
    documents=get_rts_chunks(doc=sample_document),
    embedding=EMBEDDINGS_MODEL,
    collection_name="rts_collection"
)


sem_vs = Chroma.from_documents(
    documents=get_sem_chunks(doc=sample_document),
    embedding=EMBEDDINGS_MODEL,
    collection_name="sem_collection"
)


# Test Queries 
test_queries = [
    "How do I authenticate with OAuth2?",
    "What happens when I hit the rate limit?",
    "How are webhooks secured?",
    "What format are errors returned in?"
]


def test_retrieval(query, vector_store, name):
    results = vector_store.similarity_search(query, k=1)
    print(f'\n{name} - Query: \"{query}\"')
    print(f'Retrieved: {results[0].page_content}...')
    return results[0].page_content


print(f"\n{'='*60}")
print("   Retrieval Results")
print(f"\n{'='*60}")


for query in test_queries:
    rts_result = test_retrieval(query=query, vector_store=rts_vs, name="Recursive(fixed-size)")
    sem_result = test_retrieval(query=query, vector_store=sem_vs, name="Semantic(meaning-based)")
    smart_result = test_retrieval(query=query, vector_store=smart_vs, name="Smart Chunking(semantic-with-rts-fallback)")