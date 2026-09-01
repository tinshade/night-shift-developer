import os
import chromadb
from dotenv import load_dotenv 


load_dotenv()
chroma_client = chromadb.Client()


# Create a collection
collection = chroma_client.get_or_create_collection(os.environ.get('CHROMA_DB_COLLECTION_NAME'))


# Define text documents
documents:list[dict[str,str]] = [
    {"id": "doc1", "text": "Hello, World!"},
    {"id": "doc2", "text": "How are you today?"},
    {"id": "doc3", "text": "Goodbye, see you later!"},
    
]


# Add documents to collection
for doc in documents:
    collection.upsert(ids=[doc['id']], documents=[doc["text"]])
    

# Fetch relevant documents from DB based on docs and query 
query_text:str = "Hello, World!"
results = collection.query(
    query_texts=[query_text],
    n_results=3
)

print(results)