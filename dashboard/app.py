"""
Financial Complaint Governance Engine — Streamlit Dashboard
Dark Theme Chatbot UI
"""
import os, re, uuid, json
from datetime import datetime
from dotenv import load_dotenv

import httpx
import streamlit as st

load_dotenv()
API_BASE   = os.getenv("API_BASE_URL", "http://localhost:8000")
GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

st.set_page_config(
    page_title="Complaint Assistant",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS STYLING ---
st.markdown("""
<style>
/* Dark Theme Enforcements */
[data-testid="stAppViewContainer"] { background-color: #0f0f0f; color: #e5e5e5; }
[data-testid="stSidebar"] { background-color: #1a1a1a; border-right: 1px solid #333; }
[data-testid="stSidebar"] * { color: #e5e5e5 !important; }
[data-testid="stHeader"] { background-color: transparent !important; }

/* Chat Bubbles */
.chat-bot {
    background-color: #1e1e1e;
    border-radius: 12px;
    padding: 14px 18px;
    margin: 8px 0;
    width: fit-content;
    max-width: 85%;
    border-left: 3px solid #6366f1;
    color: #e5e5e5;
}
.chat-user {
    background-color: #2e1a47;
    border-radius: 12px;
    padding: 14px 18px;
    margin: 8px 0;
    width: fit-content;
    max-width: 85%;
    margin-left: auto;
    border-right: 3px solid #a855f7;
    color: #e5e5e5;
}

/* Decision Summary Card */
.decision-card {
    background: #18181b;
    border: 1px solid #3f3f46;
    border-radius: 8px;
    padding: 16px;
    margin-top: 10px;
    color: #e5e5e5;
}
.decision-card h4 { margin-top: 0; color: #f4f4f5; margin-bottom: 8px; }
.status-Approved { color: #10b981; font-weight: bold; }
.status-Denied { color: #ef4444; font-weight: bold; }
.status-Pending { color: #f59e0b; font-weight: bold; }
.status-Escalate { color: #3b82f6; font-weight: bold; }

/* Complaint ID Box */
.cid-box {
    background: #3b0764;
    color: #e9d5ff;
    padding: 8px 12px;
    border-radius: 6px;
    font-family: monospace;
    font-weight: bold;
    display: inline-block;
    margin: 6px 0;
    border: 1px solid #9333ea;
}

/* Sidebar Active Button Override */
.active-btn {
    border: 1px solid #a855f7 !important;
    background: #2e1a47 !important;
}
</style>
""", unsafe_allow_html=True)

# --- STATE INITIALIZATION ---
if "messages" not in st.session_state:
    st.session_state.messages = []
    
if "sidebar_mode" not in st.session_state:
    st.session_state.sidebar_mode = "new_complaint" # Options: new_complaint, policies, track
    
if "complaint_registry" not in st.session_state:
    st.session_state.complaint_registry = {} # Simulates localStorage
    
if "active_cid" not in st.session_state:
    st.session_state.active_cid = None

if "mc_tab" not in st.session_state:
    st.session_state.mc_tab = "File"

# --- HELPER FUNCTIONS ---
def chat_groq(messages):
    from groq import Groq
    client = Groq(api_key=GROQ_KEY)
    
    SYSTEM_PROMPT = """You are an expert customer success AI for a financial institution resolving consumer complaints.
(a) You represent the COMPANY. Speak warmly and empathetically to the customer trying to make things right or explaining internal decisions.
(b) NEVER suggest the customer sue the company, contact the CFPB, FTC, Attorney General, or seek outside legal counsel. If their request is denied, only offer the option to escalate internally to human management.
(c) Always explain decisions in plain English, avoiding legal jargon, but cite the relevant regulation (e.g., Reg Z, FCBA, ECOA, CARD Act) as the basis for the decision.
(d) You must track and reference Complaint IDs in the format CPL-XXXXX or CPL-XXXXX-ESC.
(e) If a user returns with a valid Complaint ID, greet them by referencing their prior issue and current status.
(f) DO NOT output HTML directly unless strictly necessary. Streamlit will handle rendering decision cards.
Always end your explanation with: "Would you like to know your next steps or escalate this internally?"
"""
    sys_msg = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Inject active complaint context if it exists
    if st.session_state.active_cid and st.session_state.active_cid in st.session_state.complaint_registry:
        c_data = st.session_state.complaint_registry[st.session_state.active_cid]
        ctx = f"Context: User is inquiring about active Complaint ID {st.session_state.active_cid}. Details: {json.dumps(c_data)}"
        sys_msg.append({"role": "system", "content": ctx})
        
    # Inject policy context if in policies mode
    if st.session_state.sidebar_mode == "policies":
        sys_msg.append({"role": "system", "content": "The user is asking about Policies & Rules (Reg Z, FCBA, ECOA, CARD Act). Focus entirely on legal/regulatory guidance."})

    resp = client.chat.completions.create(
        model=GROQ_MODEL, messages=sys_msg + messages,
        max_tokens=800, temperature=0.3,
    )
    return resp.choices[0].message.content

def file_complaint(narrative, product, issue):
    """File a complaint via API or directly to registry if API fails locally"""
    # Try hitting the real API first
    try:
        r = httpx.post(
            f"{API_BASE}/evaluate/inline",
            json={"narrative": narrative, "product": product, "issue": issue},
            timeout=35,
        )
        data = r.json()
        raw_cid = data.get("complaint_id", str(uuid.uuid4())[:5])
        decision = data.get("ai_decision", "Pending")
        
        # Ask LLM for a 1-sentence crux for the UI card depending on outcome
        if data.get("status") == "resolved" and "agent_summaries" in data:
            summaries = data["agent_summaries"]
            sum_text: str = " | ".join([s.get("reasoning", "") for s in summaries])
            
            prompt = f"Summarize the core reason for the AI's decision ({decision}) using ONLY the information provided. Make it exactly ONE short, empathetic sentence directed at the customer as if you are a customer service rep. Do NOT assume a refund was asked for unless mentioned. No legal jargon.\nAgent Log: {sum_text[:1000]}"
            
            try:
                from groq import Groq
                c = Groq(api_key=GROQ_KEY)
                resp = c.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=60,
                    temperature=0.3
                )
                reason = resp.choices[0].message.content.strip().strip('"').replace("\n", " ")
            except Exception as e:
                reason = "Our governance panel has reviewed your complaint and reached a final decision."
        else:
            reason = "The evaluation is still in progress or under review."
            
    except Exception as repr_err:
        # Fallback for demo if API isn't perfectly synced
        raw_cid = str(uuid.uuid4())[:5]
        decision = "Pending"
        data = {}

    cid = f"CPL-{str(raw_cid).upper().zfill(5)}"
    
    # Map decision to action string
    if decision == "Escalate":
        action = "Escalated for manual review by Compliance Team."
    elif decision == "Monetary Relief":
        action = "Relief initiated and ticket closed."
    elif decision == "Explanation Only":
        action = "Ticket closed. Detailed explanation generated."
    elif decision == "Reject Relief":
        action = "Request denied. Ticket closed."
    else:
        action = "Case opened and pending final review."
        
    reg = data.get("guardrail_applied") if data.get("guardrail_applied") else "FCBA / Reg Z guidelines"
    
    # Store in registry
    record = {
        "id": cid,
        "product": product,
        "issue": issue,
        "narrative": narrative,
        "date": datetime.now().strftime('%Y-%m-%d'),
        "decision": decision,
        "reason": reason,
        "policy": reg,
        "action": action,
        "raw_data": data
    }
    st.session_state.complaint_registry[cid] = record
    return cid, record

def render_decision_card(record):
    """Render the HTML for the Decision Summary Card"""
    dec_val = record.get("decision", "Pending")
    status_class = "status-Pending"
    if dec_val in ["Monetary Relief", "Approved", "Explanation Only"]: status_class = "status-Approved"
    elif dec_val in ["Reject Relief", "Denied"]: status_class = "status-Denied"
    elif dec_val == "Escalate": status_class = "status-Escalate"
    
    display_status = "Explanation Given" if dec_val == "Explanation Only" else dec_val
    
    return f'''
    <div class="decision-card">
        <h4>📋 Decision Summary</h4>
        <b>Complaint ID:</b> {record.get('id', 'N/A')}<br>
        <b>Type:</b> {record.get('product', 'Unknown')} - {record.get('issue', 'Unknown')}<br>
        <b>Filed Date:</b> {record.get('date', 'Unknown')}<br>
        <b>Status:</b> <span class="{status_class}">{display_status}</span><br><br>
        <b>Reason:</b> {record.get('reason', 'N/A')}<br>
        <b>Policy & Regulation:</b> {record.get('policy', record.get('regulation', 'FCBA / Reg Z guidelines'))}<br>
        <b>Action Taken:</b> {record.get('action', 'N/A')}
    </div>
    '''

# --- SIDEBAR NAV ---
with st.sidebar:
    st.markdown("### ⚖️ Complaint Assistant")
    st.divider()
    
    # Navigation Buttons (acting as state setters)
    btn_mc = st.button("📁 New Complaint", use_container_width=True, type="primary" if st.session_state.sidebar_mode == "new_complaint" else "secondary")
    if btn_mc: 
        st.session_state.sidebar_mode = "new_complaint"
        st.rerun()
        
    btn_pr = st.button("⚖️ Policies & Rules", use_container_width=True, type="primary" if st.session_state.sidebar_mode == "policies" else "secondary")
    if btn_pr: 
        st.session_state.sidebar_mode = "policies"
        st.rerun()
        
    btn_tr = st.button("🔎 Track My Complaint", use_container_width=True, type="primary" if st.session_state.sidebar_mode == "track" else "secondary")
    if btn_tr: 
        st.session_state.sidebar_mode = "track"
        st.rerun()
        
    st.divider()

    # Dynamic Sidebar Content based on Active Module
    if st.session_state.sidebar_mode == "new_complaint":
        st.markdown("**Module Active: New Complaint**")
        scol1, scol2 = st.columns(2)
        if scol1.button("File", use_container_width=True): st.session_state.mc_tab = "File"
        if scol2.button("Understand", use_container_width=True): st.session_state.mc_tab = "Understand"
        
        st.markdown(f"*{st.session_state.mc_tab} View selected. Please use the main panel.*")
                        
        if st.session_state.mc_tab == "Understand":
            if st.session_state.active_cid and st.session_state.active_cid in st.session_state.complaint_registry:
                st.success(f"Active ID: {st.session_state.active_cid}")
                record = st.session_state.complaint_registry[st.session_state.active_cid]
                st.markdown(f"**Product:** {record['product']}")
                st.markdown(f"**Status:** {record['decision']}")
                st.markdown("Use the chat panel to ask for plain English explanations of this decision.")
            else:
                st.info("No active complaint loaded. Please file a new complaint or use 'Track My Complaint' to load an existing one.")

    elif st.session_state.sidebar_mode == "policies":
        st.markdown("**Module Active: Policies & Rules**")
        st.info("The chat context is now set to Policy Guidance. Ask questions about Reg Z, FCBA, ECOA, or CARD Act in the main chat area.")

    elif st.session_state.sidebar_mode == "track":
        st.markdown("**Module Active: Track Complaint**")
        track_id = st.text_input("Enter Complaint ID (CPL-XXXXX)")
        if st.button("Load History", use_container_width=True):
            if track_id in st.session_state.complaint_registry:
                st.session_state.active_cid = track_id
                st.success("Thread loaded! Resuming chat.")
                record = st.session_state.complaint_registry[track_id]
                status = record.get("decision", "Pending")
                if status == "Pending":
                    msg = f"You've returned with a valid Complaint ID, {track_id}. The current status of your complaint regarding {record['issue']} is that it's still pending review. How else can I assist you today?"
                else:
                    msg = f"Welcome back! I've loaded your complaint `[ID: {track_id}]` regarding your {record['issue']}. The decision is currently {status}. How can I assist you with this today?"
                
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": msg
                })
            else:
                st.error("Complaint ID not found in local registry.")

# --- MAIN PANEL ---
if st.session_state.sidebar_mode == "new_complaint" and st.session_state.mc_tab == "File":
    st.header("📝 File a New Complaint")
    st.markdown("Please provide the details of your issue below.")
    
    with st.form("file_comp_form", clear_on_submit=True):
        product = st.selectbox("Product", ["Credit card", "Prepaid card", "Checking or savings account", "Debt collection", "Mortgage", "Student loan"])
        issue = st.selectbox("Issue", [
            "Getting a credit card",
            "Billing disputes", 
            "Fees or interest", 
            "Fraudulent charge", 
            "Problem with a purchase shown on your statement",
            "Closing your account",
            "Other"
        ])
        narrative = st.text_area("Complaint Description", height=200, placeholder="Explain what happened in detail...")
        submitted = st.form_submit_button("Submit Complaint", use_container_width=True)
        
        if submitted and narrative.strip():
            with st.spinner("Processing with our AI Governance Panel..."):
                cid, record = file_complaint(narrative.strip(), product, issue)
                st.session_state.active_cid = cid
                
                # Add a system message effectively "from the bot" confirming the submission
                bot_msg = f'Thank you for submitting your complaint. I have generated your unique Complaint ID: <br><div class="cid-box">{cid}</div><br>Save this ID. Use it to resume this conversation or check back with us in 5–7 business days.<br>'
                bot_msg += render_decision_card(record)
                bot_msg += "<br>Would you like to know your next steps or escalate this?"
                
                st.session_state.messages.append({"role": "assistant", "content": bot_msg, "is_html": True})
                st.session_state.mc_tab = "Understand" # Auto-switch tab
                st.rerun()

else:
    # --- CHAT PANEL (MAIN) ---
    # Welcome message if empty
    if not st.session_state.messages:
        st.session_state.messages.append({"role": "assistant", "content": "Welcome to the CFPB Complaint Assistant. How can I help you today? You can file a new complaint, track an existing one, or ask about financial regulations."})

    # Render Chat History
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
        else:
            # Check if we need to render HTML natively or just text
            content = msg["content"]
            if msg.get("is_html") or "<div" in content:
                st.markdown(f'<div class="chat-bot">🤖 {content}</div>', unsafe_allow_html=True)
            else:
                # Add some formatting for IDs naturally created by the AI
                content = re.sub(r'(CPL-\d{5}(?:-ESC)?)', r'<span class="cid-box">\1</span>', content)
                st.markdown(f'<div class="chat-bot">🤖 {content}</div>', unsafe_allow_html=True)

    # Chat Input at bottom
    if prompt := st.chat_input("Enter your message..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # Auto-detect CPL ID in user message and set active
        ids_in_msg = re.findall(r"\b(CPL-\d{5}(?:-ESC)?)\b", prompt)
        if ids_in_msg:
            detected_id = ids_in_msg[0]
            if detected_id in st.session_state.complaint_registry:
                st.session_state.active_cid = detected_id
                st.session_state.sidebar_mode = "new_complaint"
                st.session_state.mc_tab = "Understand"
        
        # Get AI Response
        api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
        
        with st.spinner("Consulting Governance Panel..."):
            try:
                reply = chat_groq(api_messages)
            except Exception as e:
                reply = f"⚠️ Error consulting the panel: {str(e)}"
                
        # Auto-detect if User wants to Escalate
        if "escalate" in prompt.lower() and st.session_state.active_cid:
            if not st.session_state.active_cid.endswith("-ESC"):
                new_id = f"{st.session_state.active_cid}-ESC"
                st.session_state.complaint_registry[new_id] = st.session_state.complaint_registry[st.session_state.active_cid].copy()
                st.session_state.complaint_registry[new_id]["id"] = new_id
                st.session_state.complaint_registry[new_id]["decision"] = "Escalate"
                st.session_state.complaint_registry[new_id]["action"] = "Case has been escalated to human review and management."
                st.session_state.active_cid = new_id
                
                # Inject Decision Card into AI reply
                card_html = render_decision_card(st.session_state.complaint_registry[new_id])
                reply += f"<br><br>{card_html}"
                
        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.rerun()
