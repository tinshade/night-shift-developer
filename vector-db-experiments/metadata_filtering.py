
from utils import create_vector_store
from langchain_chroma import Chroma
import tempfile
import gc



def metadata_filtering():
    with tempfile.TemporaryDirectory() as tmpdir:
        
        # Create a vector store from documents
        vector_store = create_vector_store(chroma_client=Chroma, dir=tmpdir)
        query = "What databases are available?"
        filter_criteria = {"topic": "database"}
        
        # Ensure you filter by topic to narrow-down the search and get more relevant results
        filtered_results = vector_store.similarity_search(
            query, k=5, filter=filter_criteria # Remove the filter and see how the results are impacted
        )
        print(f"\nResults with metadata filtering for query '{query}':")
        for i, doc in enumerate(filtered_results):
            print(
                f"Result {i+1}: {doc.page_content} (Source: {doc.metadata['source']})"
            )
        
        vector_store.delete_collection()
        del vector_store
        gc.collect()


if __name__ == "__main__":
    metadata_filtering()