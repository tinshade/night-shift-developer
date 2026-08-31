import os
from dotenv import load_dotenv
import tempfile
from pathlib import Path
from langchain_community.document_loaders import (TextLoader, PyPDFLoader)

load_dotenv()


def load_text_file():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as temp_file:
        temp_file.write(b"Hello, this is a sample text file.\nThis file is used to demo document loading")
        temp_file_path = temp_file.name


    try:
        loader = TextLoader(temp_file_path)
        documents = loader.load()

        for doc in documents:
            print("doc", doc)
            print(doc.page_content)
    finally:
        os.remove(temp_file_path)


def pdf_loader(pdf_path):
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    print(f"Loaded {len(documents)} document(s) from PDF")
    for i, doc in enumerate(documents):
        print(f"Document {i+1} Content Preview: {doc.page_content[:1]}")
        print(f"Metadata: {doc.metadata}")



if __name__ == "__main__":
    #load_text_file()
    pdf_documents = os.path.join(os.getcwd(),'pdfs')
    for _r,_d,files in os.walk(pdf_documents):
        for file in files:
            pdf_loader(os.path.join(pdf_documents, file))
