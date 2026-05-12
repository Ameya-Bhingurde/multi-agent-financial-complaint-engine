# ── HuggingFace Spaces — Multi-Agent Financial Complaint Governance Engine ──
# Runs the FULL stack inside one container:
#   Qdrant (:6333) + PageIndex (:8001) + FastAPI (:8000) + Streamlit (:7860)
# Only infra change vs local: PostgreSQL → SQLite  (DATABASE_URL env var)

FROM python:3.11-slim

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor curl wget sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Qdrant binary
RUN wget -q https://github.com/qdrant/qdrant/releases/download/v1.11.4/qdrant-x86_64-unknown-linux-musl.tar.gz \
    -O /tmp/qdrant.tar.gz \
    && tar -xzf /tmp/qdrant.tar.gz -C /usr/local/bin \
    && rm /tmp/qdrant.tar.gz \
    && chmod +x /usr/local/bin/qdrant

WORKDIR /app

# Python deps (split into layers for cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model so container starts fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# Copy entire project
COPY . .

# Create data directories
RUN mkdir -p /data/qdrant /data/qdrant_storage /tmp/qdrant_config

# Write Qdrant config (use /data/qdrant_storage for persistent vector data)
RUN cat > /tmp/qdrant_config/config.yaml << 'EOF'
storage:
storage_path: /data/qdrant_storage
service:
host: 0.0.0.0
http_port: 6333
grpc_port: 6334
EOF

# Supervisor config
COPY deploy/supervisord.conf /etc/supervisord.conf

# Startup script
COPY deploy/startup.sh /startup.sh
RUN chmod +x /startup.sh

# HuggingFace Spaces exposes port 7860
EXPOSE 7860

ENV PYTHONPATH=/app \
    DATABASE_URL=sqlite:////data/complaints.db \
    QDRANT_HOST=localhost \
    QDRANT_PORT=6333 \
    PAGEINDEX_URL=http://localhost:8001 \
    API_BASE_URL=http://localhost:8000 \
    LLM_PROVIDER=groq \
    GROQ_MODEL=llama-3.3-70b-versatile \
    HF_SPACE=true

ENTRYPOINT ["/startup.sh"]
