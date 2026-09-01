from langchain_chroma import Chroma
from utils import create_vector_store
import tempfile
import gc

def similarity_search_with_scores():
    with tempfile.TemporaryDirectory() as tmpdir:
        vector_store = create_vector_store(chroma_client=Chroma, dir=tmpdir)
        query = "Explain vector stores."
        results_with_scores = vector_store.similarity_search_with_score(query, k=3)
        print(f"Top 3 results with scores for query: '{query}':")
        for idx, (doc,score) in enumerate(results_with_scores):
            print(
                f"Result {idx+1}: {doc.page_content} (Distance Score: {score:.4f}), (Similarity Score: {(1/(1+score)):.4f}) Source: {doc.metadata['source']})" 
                # These are based on distance and not similarity. The closer the result is to 0, the better that output is
                # Similarity = 1/(1 + distance) or 1 - (distance / max_distance)
                
            )
        
        # Explicitly release ChromaDB
        vector_store.delete_collection()
        del vector_store
        gc.collect()

if __name__ == "__main__":
    similarity_search_with_scores()