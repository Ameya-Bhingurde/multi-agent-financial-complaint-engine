# Multi-Agent Financial Complaint Governance Engine - Presentation Information

## 1: Introduction
*   **Brief overview of the project:** A production-grade agentic system that evaluates consumer complaints using real CFPB (Consumer Financial Protection Bureau) resolution data, enforces policy constraints, and produces audit-ready decision recommendations.
*   **Problem statement:** Manual processing of large volumes of complex financial complaints is slow, prone to inconsistency, and carries a high risk of non-compliance with strict regulatory frameworks (such as FCRA, ECOA).
*   **Objectives of the project:** To automate complaint evaluation, enforce policy constraints deterministically, provide transparent and explainable decision recommendations, and optimize consistency across various concerns including fairness, financial impact, fraud, and reputation.

## 2: Literature Review
*   **Existing solutions and research background:** Traditional approaches rely on either rigid rule-based systems or single Large Language Models (LLMs) for text classification and decision support. 
*   **Gaps identified in the current methods:** Single LLMs struggle with multi-objective optimization (e.g., balancing regulatory compliance vs. financial impact). Rule-based systems cannot comprehend the nuances of natural language narratives. Furthermore, pure generative AI solutions lack the deterministic guardrails required for guaranteed regulatory compliance.

## 3: Proposed Solution
*   **Description of your approach:** A "Five-Agent Governance Panel" where 5 parallel LLM agents act as distinct personas (Regulatory Compliance, Fairness, Financial Impact, Fraud Pattern, Reputation Risk) to evaluate each complaint. A Debate & Aggregation Engine reconciles their scores, strictly bounded by Deterministic Guardrails (e.g., force an escalation if a regulatory violation is detected).
*   **How it improves upon existing solutions:** The multi-agent debate mechanism ensures more balanced and comprehensively analyzed decisions. Deterministic guardrails guarantee that hard constraints are never breached by AI hallucinations, making the system suitable for highly regulated environments.

## 4: Methodology
*   **System architecture / Workflow diagram:** 
    *   **Ingestion:** CFPB REST API/CSV → n8n Ingestion Workflow → PostgreSQL.
    *   **Indexing:** PageIndex Service (Hierarchical Segmentation) → Embedding Service → Qdrant (Vector Store).
    *   **Evaluation:** Streamlit Dashboard/API Client → FastAPI → PageIndex Retriever → Context Builder → 5 Parallel LLM Agents → Debate & Aggregation Engine.
    *   **Storage & Metrics:** Decision Log → PostgreSQL → Evaluator (vs CFPB Actual Outcomes) → Metrics Loop.
*   **Tools, technologies, and frameworks used:** Python, FastAPI, Streamlit, PostgreSQL (Structured Data), Qdrant (Vector DB), n8n (Orchestration), Docker, LLM APIs (Groq Llama 3, OpenAI GPT-4o, Ollama), Embedding Models (BGE-small).
*   **Implementation steps:**
    1.  Data ingestion and structuring via n8n and DB.
    2.  Document segmentation, embedding, and indexing into Qdrant.
    3.  Implementation of parallel LLM agent personas and deterministic guardrails.
    4.  Development of the Debate and Aggregation logic.
    5.  Creation of the FastAPI backend and Streamlit dashboard UI.
    6.  Setup of the evaluation and continuous calibration loops.

## 5: Experimental Setup & Dataset (if applicable)
*   **Description of dataset used:** Real consumer complaint data from the Consumer Financial Protection Bureau (CFPB), including structured metadata and unstructured consumer narratives (e.g., sample of 500 Credit Card complaints).
*   **Experiment configurations and parameters:** 
    *   Configurable LLM providers via environment variables (Groq, OpenAI, Ollama).
    *   Debate Threshold parameter: triggers a second round of deliberation if the standard deviation of agent scores is too high.
    *   Weighted agent scoring: Regulatory (30%), Fairness (20%), Financial Impact (20%), Fraud Pattern (20%), Reputation Risk (10%).

## 6: Implementation & Features
*   **Screenshots or demo of the system:** *(Include screenshots of the Streamlit Consumer Complaint Assistant UI, Decision Detail views, and Metrics dashboard here during the presentation).*
*   **Key functionalities of the project:**
    *   Automated ingestion workflow (n8n).
    *   Metadata-filtered semantic vector search.
    *   Parallel evaluation by 5 specialized AI personas.
    *   Deterministic overrides for critical risk levels (e.g., `fraud_score >= 8`).
    *   Interactive UI for inspecting agent reasoning and audit logs.

## 7: Results & Analysis
*   **Performance metrics:** Evaluated against actual CFPB company responses using standards such as Accuracy (overall agreement rate), Precision (correct relief recommendations), Recall, and Dispute Prediction Accuracy.
*   **Comparisons with existing methods:** AI consensus decisions are directly calibrated and compared against historical, real-world CFPB outcomes to demonstrate improved or parallel reliability.
*   **Graphs, tables, or charts:** *(Include dashboard metric charts, agent agreement heatmaps, and accuracy over time graphs here).*

## 8: Challenges & Limitations
*   **Issues faced during development:** Managing LLM context windows to fit complex, multi-page complaint narratives alongside metadata and retrieval contexts. Coordinating fast, parallel LLM inference effectively to avoid UI timeouts.
*   **Limitations of the proposed solution:** The system's contextual understanding is ultimately bounded by the quality and exhaustiveness of the consumer-provided narratives. Reliance on external APIs (like OpenAI or Groq) introduces potential latency dependencies.

## 9: Conclusion
*   **Summary of findings:** A multi-agent evaluation panel combined with deterministic guardrails yields a significantly more robust, compliant, and explainable decision engine than monolithic LLM evaluations.
*   **Key takeaways from the project:** Orchestrating targeted debate among AI personas leads to refined, audit-ready reasoning. In highly regulated financial spaces, AI must be paired with hard rules (guardrails) to ensure safety and trust.

## 10: References
*   Consumer Financial Protection Bureau (CFPB) Complaint Database.
*   Documentation for FastAPI, PostgreSQL, Qdrant, Streamlit, n8n, Groq Platform, and OpenAI APIs.
