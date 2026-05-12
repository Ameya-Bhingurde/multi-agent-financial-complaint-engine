"""
Policy Indexer — indexes real credit card T&C documents into Qdrant.
"""
import os, sys, re, logging, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from embeddings.embedding_service import embed_batch
from embeddings.qdrant_store import upsert_vectors

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("policy_indexer")

POLICIES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policies")

SOURCE_MAP = {
    "cfpb_regulatory_framework.txt":         ("CFPB",        "US Federal Regulation"),
    "chase_credit_card_agreement.txt":        ("Chase",       "Chase Sapphire/Freedom"),
    "capital_one_credit_card_agreement.txt":  ("Capital One", "CapOne Venture/Quicksilver"),
    "citibank_credit_card_agreement.txt":     ("Citibank",    "Citi Double Cash/Premier"),
}

def chunk_policy(text: str, issuer: str, source: str) -> list[dict]:
    chunks = []
    blocks = re.split(r"\n(?=SECTION \d+:)", text)
    for block in blocks:
        if not block.strip():
            continue
        sub_blocks = re.split(r"\n(?=\d+\.\d+ [A-Z])", block)
        for sub in sub_blocks:
            sub = sub.strip()
            if len(sub) < 100:
                continue
            first_line = sub.split("\n")[0].strip()
            chunks.append({
                "text":         sub,
                "section_type": "policy",
                "source":       source,
                "issuer":       issuer,
                "section":      first_line[:120],
                "product":      "Credit card",
                "issue_type":   "policy_document",
            })
    return chunks

def index_all_policies():
    logger.info("Loading embedding model...")
    total    = 0

    for filename, (issuer, source) in SOURCE_MAP.items():
        path = os.path.join(POLICIES_DIR, filename)
        if not os.path.exists(path):
            logger.warning(f"Missing: {path}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_policy(text, issuer, source)
        logger.info(f"{filename}: {len(chunks)} chunks")
        texts    = [c["text"] for c in chunks]
        vectors  = embed_batch(texts)
        points   = [
            {"id": str(uuid.uuid4()), "vector": vec, "payload": {k: v for k, v in c.items() if k != "text"}}
            for c, vec in zip(chunks, vectors)
        ]
        upsert_vectors(points)
        total += len(chunks)
        logger.info(f"  ✅ {filename} indexed.")

    logger.info(f"Done — {total} policy chunks in Qdrant.")
    return total

if __name__ == "__main__":
    index_all_policies()
