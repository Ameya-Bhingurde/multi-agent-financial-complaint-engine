FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only what this service needs
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    sqlalchemy==2.0.35 \
    psycopg2-binary==2.9.9 \
    qdrant-client==1.11.1 \
    sentence-transformers==3.1.1 \
    torch==2.4.1 \
    openai==1.47.0 \
    python-dotenv==1.0.1 \
    pydantic==2.8.2

# Copy source
COPY db/         ./db/
COPY embeddings/ ./embeddings/
COPY pageindex/  ./pageindex/

# Expose port
EXPOSE 8001

# Run the FastAPI microservice
CMD ["uvicorn", "pageindex.service:app", "--host", "0.0.0.0", "--port", "8001"]
