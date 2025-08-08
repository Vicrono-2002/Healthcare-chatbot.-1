from src.helper import load_pdf, split_text, download_embeddings
from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec
from langchain_pinecone import PineconeVectorStore
from dotenv import load_dotenv
import os

# Load environment variables (optional if you prefer .env instead of hardcoding)
load_dotenv()

#  Define your data directory
data_dir = "Data/"  # make sure this exists and has PDFs

# ✅Pinecone API Key
PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')
os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY

# Load and process data
extracted_data = load_pdf(data=data_dir)
text_chunks = split_text(extracted_data)
embeddings = download_embeddings()

#  Initialize Pinecone
pc = Pinecone(api_key=PINECONE_API_KEY)

index_name = "healthcare-chatbot"

#  Create Pinecone index (will throw error if index already exists)
if index_name not in [index.name for index in pc.list_indexes()]:
    pc.create_index(
        name=index_name,
        dimension=384,  
        metric="cosine",
        spec=ServerlessSpec(
            cloud="aws",
            region="us-east-1"
        )
    )


#  Upload embeddings to Pinecone
docsearch = PineconeVectorStore.from_documents(
    documents=text_chunks,
    index_name=index_name,
    embedding=embeddings,
)
