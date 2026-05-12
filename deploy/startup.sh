#!/bin/bash
set -e

echo "========================================="
echo " Starting CFPB Governance Engine...      "
echo "========================================="

# 1. Initialize SQLite Database
echo "[1/4] Initializing Database (SQLite at /data/complaints.db)..."
mkdir -p /data
# Give it a second just in case disk is slow to mount
sleep 1
python3 -c "from db.session import init_db; init_db()"
echo "      Database tables created."

# 2. Seed data if DB is empty (first boot on HF Space)
echo "[2/4] Checking if DB needs seeding..."
DB_COUNT=$(python3 -c "
from db.session import SessionLocal
from db.models import Complaint
db = SessionLocal()
print(db.query(Complaint).count())
db.close()
" 2>/dev/null || echo "0")

if [ "$DB_COUNT" -eq "0" ]; then
    echo "      DB is empty. Seeding 100 sample complaints..."
    python3 ingestion/run_ingestion.py --limit 100
    echo "      Seeding complete."
else
    echo "      DB already contains $DB_COUNT complaints. Skipping seeding."
fi

# 3. Start Supervisord (which launches Qdrant, PageIndex, FastAPI, and Streamlit)
echo "[3/4] Starting Supervisord for microservices..."
/usr/bin/supervisord -c /etc/supervisord.conf &
SUPERVISOR_PID=$!

# Wait for Qdrant to start (port 6333)
echo -n "      Waiting for Qdrant... "
for i in {1..30}; do
    if curl -s http://localhost:6333 > /dev/null; then
        echo "Ready!"
        break
    fi
    sleep 1
done

# 4. Index data into Qdrant if needed
echo "[4/4] Checking if Qdrant needs indexing..."
QDRANT_COUNT=$(curl -s http://localhost:6333/collections/complaint_pages | grep -o '"points_count":[0-9]*' | cut -d':' -f2 || echo "0")

if [ "$QDRANT_COUNT" -eq "0" ] || [ -z "$QDRANT_COUNT" ]; then
    echo "      Qdrant is empty. Indexing seeded complaints..."
    # Give PageIndex microservice another few seconds to fully spin up
    sleep 3 
    python3 pageindex/run_indexing.py
    echo "      Indexing complete."
else
    echo "      Qdrant contains $QDRANT_COUNT vectors. Skipping indexing."
fi

echo "========================================="
echo " System fully initialized!               "
echo " Streaming logs from supervisord...      "
echo "========================================="

# Keep container alive by waiting on supervisord
wait $SUPERVISOR_PID
