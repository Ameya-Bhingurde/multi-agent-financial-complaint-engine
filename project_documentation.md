# Multi-Agent Financial Complaint Governance Engine

## 1: Introduction

### 1.1 Brief Overview of the Project
The **Multi-Agent Financial Complaint Governance Engine** is a production-grade, agentic enterprise system designed to automate the evaluation of complex consumer financial complaints. By utilizing real-world resolution data from the Consumer Financial Protection Bureau (CFPB), the platform acts as an automated governance panel. It rigorously enforces corporate policy and regulatory constraints, and ultimately produces fully explainable, audit-ready decision recommendations regarding consumer relief and remediation. 

### 1.2 Problem Statement
Handling massive volumes of consumer financial disputes manually introduces significant challenges for modern banking institutions. Human review is slow, fundamentally subjective, and prone to costly inconsistencies across different analysts. Most critically, any oversight in evaluating a complaint against strict regulatory frameworks (like the CFPB regulations, the Fair Credit Reporting Act (FCRA), or the Equal Credit Opportunity Act (ECOA)) carries immense legal and financial risk. There is a pressing need for a system capable of interpreting nuanced natural language narratives while consistently adhering to non-negotiable compliance rules.

### 1.3 Objectives of the Project
*   **Automated, Multi-Faceted Evaluation:** To process unstructured consumer complaints by evaluating them simultaneously across multiple critical business dimensions (Compliance, Fairness, Fraud, etc.).
*   **Deterministic Safety:** To enforce strict policy constraints (guardrails) deterministically, ensuring generative AI never hallucinates a non-compliant or illegal recommendation.
*   **Auditability & Transparency:** To provide an explainable "debate trail" for every AI decision, allowing human reviewers to trace exactly why a specific recommendation (e.g., *Monetary Relief* vs. *Escalate*) was generated.
*   **Operational Efficiency:** To dramatically reduce the time-to-resolution for complex disputes while maximizing the consistency of the outcomes.


## 2: Literature Review

### 2.1 Existing Solutions and Research Background
Historically, automated dispute routing mechanisms have fallen into two main categories:
1.  **Rule-Based Keyword Systems:** Traditional systems rely on dense networks of regular expressions and rigid keyword matching. Examples include flagging any complaint with the words "attorney" or "sue" for immediate escalation.
2.  **Single-Model Machine Learning Classifiers:** Recent applications have deployed standalone text classifiers (like fine-tuned BERT models or single Large Language Models) that take a complaint narrative as input and output a basic binary classification label (e.g., Valid or Invalid).

### 2.2 Gaps Identified in Current Methods
*   **Multi-Objective Conflicts:** Single-model approaches inherently struggle with multi-objective optimization. A single LLM attempting to simultaneously optimize for minimum financial loss, maximum regulatory compliance, and equitable fairness often produces confused or heavily biased reasoning.
*   **Lack of Contextual Nuance in Rules:** Rule-based architectures are brittle and completely lack semantic understanding. A customer stating, *"I am absolutely NOT going to sue you, I just want a refund,"* might trigger a false-positive escalation in a keyword system looking for the phrase "sue".
*   **The Hallucination Risk:** Unbounded Generative AI cannot be trusted with final authority in heavily regulated spaces. Without programmatic constraints, LLMs may offer unwarranted financial compensation or mistakenly dismiss a severe regulatory violation.


## 3: Proposed Solution

### 3.1 Description of the Approach
To overcome the limitations of isolated LLMs and rigid rulesets, this project proposes a **Five-Agent Governance Panel**. In this architecture, an incoming complaint is not evaluated by one monolithic model, but by 5 separate, specially prompted LLM "personas" running in parallel:
1.  **Regulatory Compliance Agent (30% weight):** Screens solely for CFPB, FCRA, and ECOA violations.
2.  **Fairness Agent (20% weight):** Analyzes disparate impact and discriminatory treatment.
3.  **Financial Impact Agent (20% weight):** Assesses monetary harm, billing errors, and corporate liability.
4.  **Fraud Pattern Agent (20% weight):** Looks for indicators of unauthorized transactions or identity theft based on historical evidence.
5.  **Reputation Risk Agent (10% weight):** Estimates media risk and likelihood of severe public escalation.

### 3.2 How It Improves Upon Existing Solutions
*   **The Debate Mechanism:** The system utilizes an aggregation engine that calculates the standard deviation of the scores returned by the 5 agents. If the deviation exceeds a defined threshold (e.g., `std_dev > 2.0`), a **Round 2 Debate** is initiated. In this second round, the diverse agents are provided with the reasoning of their peers, forcing them to re-evaluate their stance before submitting a final score. 
*   **Deterministic Guardrails:** Hard-coded, programmatic interventions exist *outside* the LLMs' control. For example, if the Regulatory Agent flags `regulatory_violation_detected` or the Fraud Agent scores >= 8 with `high_score_low_evidence`, the system bypasses the weighted average completely and forces an immediate standard response (such as *Escalate* or *Reject Relief*).


## 4: Methodology

### 4.1 System Architecture and Workflow Diagram
```text
[CFPB REST API / CSV Data Fetcher]
        ↓
[n8n Automation Ingestion Workflow]
        ↓
[PostgreSQL Database — Structured Metadata Storage]
        ↓
[PageIndex Service — Hierarchical Document Segmentation] 
        ↓  (Generates Header + Narrative Chunks + Keywords)
[Embedding Service — BGE-small (Local) / OpenAI]
        ↓
[Qdrant — Metadata-Tagged Vector Store]
─────────────────────────────────────────────────────────────
[Streamlit Frontend Dashboard / API Client]
        ↓
[FastAPI Backend Application]
        ↓
[PageIndex Context Builder — Assembles <=512 token limits]
        ↓
[5 Parallel LLM Agents — Groq Llama3 / OpenAI GPT-4o]
        ↓
[Debate & Aggregation Engine] -> Analyzes Confidence / Std. Dev
        ↓
[Final Decision + Guardrail Application + Audit Log] -> Saved to DB
```

### 4.2 Tools, Technologies, and Frameworks Used
*   **Language & Backend:** Python 3.11, FastAPI (REST framework).
*   **Databases:** PostgreSQL (Relational/Structured), Qdrant (Vector Database for similarity search), SQLite (for portable HuggingFace deployment).
*   **Orchestration:** n8n (Workflow automation for daily/weekly ingestion), Docker & `docker-compose`.
*   **AI / Machine Learning:** 
    *   **LLM Inference:** Groq Cloud Platform (Llama 3 70B), OpenAI (GPT-4o), Ollama (Local fallback).
    *   **Embeddings:** HuggingFace `BAAI/bge-small-en-v1.5`.
*   **User Interface:** Streamlit (Python-based interactive dashboards).

### 4.3 Implementation Steps
1.  **Data Ingestion (`ingestion/cfpb_fetcher.py`):** Scripting API requests against the public CFPB database to extract Credit Card complaints with narrative text length > 50 characters. Normalization of API shapes into unified schemas.
2.  **Hierarchical Parsing (`pageindex/page_parser.py`):** Splitting texts logically. Separating 'header' properties (Product, Issue), chunking the main 'narrative' safely at sentence boundaries to fit ~512 token limits, and creating a 'tags' segment utilizing domain-specific dictionaries (e.g., `billing_dispute`, `account_closure`).
3.  **Vector Indexing:** Passing the segmented text through BGE-small embeddings and storing vectors alongside extensive structural metadata into Qdrant.
4.  **Agent Definition & Parallel Execution:** Creating base LLM agents and deploying them as 5 concurrent threads (`agents/aggregator.py`). 
5.  **Debate & Guardrails Assembly:** Building the logic for calculating variance penalties, applying static `risk_flags`, and deciding strictly between *Monetary Relief*, *Explanation Only*, *Reject Relief*, or *Escalate*.
6.  **UI & Metrics Generation:** Exposing all functionality via FastAPI and building visual interfaces in Streamlit to expose accuracy/recall metrics vs actual historical CFPB company responses.


## 5: Experimental Setup & Dataset

### 5.1 Description of Dataset Used
The engine utilizes the **Consumer Complaint Database** maintained by the Consumer Financial Protection Bureau (CFPB). Specifically, the pipeline initially fetches samples of 500+ *Credit Card* related complaints that natively contain unstructured "Consumer Complaint Narratives", ensuring real-world complexity, typos, and emotional vernacular are tested against the system. Historical 'Company Response' columns are withheld from the agents and used solely for ground-truth evaluation.

### 5.2 Experiment Configurations and Parameters
The Aggregation Engine is configured using several sensitive hyperparameters that can be tuned based on business risk appetite:
*   **Debate Threshold (`DEBATE_THRESHOLD` = 2.0):** The standard deviation of the five 1-10 scores required to trigger a second "peer review" negotiation round.
*   **Cold Start Penalty (`COLD_START_PENALTY` = 0.15):** An artificial reduction in AI target confidence if the system identifies the complaint is referencing new, un-indexed subject matter.
*   **Agent Weightings:** Regulatory (30%), fairness (20%), Financial Impact (20%), Fraud Pattern (20%), Reputation Risk (10%). Adjusting these dramatically shifts the final outcome map.
*   **Context Chunk Size:** Limited to 512 tokens (~2048 characters) per narrative chunk to prevent LLM attention degradation ("lost in the middle" syndrome).


## 6: Implementation & Features

### 6.1 Demonstration of the System
*(During presentations, interact with the **Consumer Complaint Assistant UI** via Streamlit. Demonstrate clicking a specific complaint from the queue, reviewing the extracted metadata, opening the "Decision Summary" card to view the dynamic resolution, and expanding the "Debate Log" to view how the 5 agents negotiated)*

### 6.2 Key Functionalities of the Project
*   **Automated Pipeline:** Self-sustaining n8n pipelines capable of digesting new CFPB data nightly without technical intervention.
*   **Parallel Multi-Agent Evaluation:** Real-time concurrent asynchronous calls to 5 different LLM system-prompts, significantly reducing latency compared to serial prompting.
*   **Dynamic Context Retrieval:** A custom PageIndex retrieval algorithm that assembles prompts combining the immediate complaint narrative with related historical precedents pulled from Qdrant.
*   **Deterministic Safety Overrides:** Hard-coded guardrails map specific LLM-detected categorical behaviors (e.g., the presence of the `ecoa_violation` tag) entirely outside of probabilistic calculation, instantly overriding scoring to ensure compliance.


## 7: Results & Analysis

### 7.1 Performance Metrics
The system incorporates an inline Evaluator that automatically tests the AI consensus decision against the historical "Company response to consumer" found in the CFPB dataset. Key metrics tracked include:
*   **Accuracy:** Overall agreement rate between the AI's final decision vs the historical company's decision.
*   **Precision and Recall:** Specifically targeting the prediction of *Monetary Relief* cases.
*   **Dispute Prediction:** Identifying if the AI can accurately forecast whether a given complaint logic will eventually result in a "Consumer Disputed = Yes" flag in the historical data.

### 7.2 Comparisons with Existing Methods
By mapping AI decisions against historical CFPB responses across standard timeframes, the Multi-Agent approach demonstrates dramatically less "false-positive relief" issuance than a standard, untuned GPT-4 session, largely attributed to the explicit weighting rules and the secondary debate rounds smoothing out individual agent hallucination spikes. 

### 7.3 Visual Analysis
*(Presentation Note: Feature the 'Metrics' page of the Streamlit dashboard here. Highlight graphs demonstrating overall model Accuracy tracked over time, and heatmap tables showcasing the correlation matrix between the 5 specific agents—e.g., showing how often the Fraud Agent disagrees with the Financial Agent).*


## 8: Challenges & Limitations

### 8.1 Issues Faced During Development
*   **Context Window Engineering:** Determining the most performant way to feed multi-page documents alongside large blocks of "peer reasoning" and "historical context" into the debate round required aggressive truncation handling and the invention of the `PageIndex` hierarchical segmenter to prevent token-limit exhaustion.
*   **Latency in Debate Rounds:** Serial execution of multi-stage LLM chains often results in 30-45 second wait times. Implementation of `concurrent.futures.ThreadPoolExecutor` was critically required to parallelize Round 1 voting down to the speed of the single slowest agent.

### 8.2 Limitations of the Proposed Solution
*   **"Garbage In, Garbage Out":** The system's ability to offer fair financial relief relies entirely on the comprehensiveness of the consumer's written narrative. If a consumer provides 3 words of context, the system has no external integration to verify internal bank ledger data.
*   **API Latency & Dependency:** Relying on API-driven LLMs (Groq, OpenAI) means external outages immediately pause internal processing. (Mitigated partially by the ability to toggle to a local, offline Ollama fallback defined in `.env`).


## 9: Conclusion

### 9.1 Summary of Findings
The use of a Multi-Agent Evaluation platform successfully proves that generative AI can be rigorously chained to produce highly structured, reliable outcomes even within heavily regulated environments. By dividing the problem into specialized AI personas and scoring the variance between them, the platform exposes the reasoning mathematically, converting "black box AI" into a transparent audit trail.

### 9.2 Key Takeaways from the Project
1.  **Orchestrated Debate Enhances Reliability:** Forcing distinct AI personas to "debate" boundary-case scenarios fundamentally improves the quality of the final outcome and reduces unprompted hallucination.
2.  **AI Must Have Guardrails in Finance:** Probabilistic engines (LLMs) must be supervised by deterministic rules (code). Integrating non-negotiable overrides (e.g., automatically escalating on regulatory triggers) is the only path to deploying LLMs in compliance-strict industries.


## 10: References
1.  **Consumer Financial Protection Bureau (CFPB):** Public Complaint API & Datasets. `https://www.consumerfinance.gov/data-research/consumer-complaints/`
2.  **n8n Documentation:** Advanced workflow automation mapping.
3.  **Qdrant Documentation:** Architecture and payload indexing for Vector Databases.
4.  **HuggingFace:** `BAAI/bge-small-en-v1.5` localized embedding models.
5.  **Groq Platform / Llama 3:** High-speed, inference architectures for production environments. 
6.  **Extracted internal code files:** `cfpb_fetcher.py`, `page_parser.py`, `aggregator.py` utilized for architectural diagrams and threshold specifications.
