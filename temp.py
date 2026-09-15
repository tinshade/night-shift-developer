import os

repos = ("langchain-experiments","log-watcher","rag-experiments","vector-db-experiments",)


for each in repos:
    directory = os.path.join(os.getcwd(), each)
    os.remove(directory)