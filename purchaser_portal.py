import streamlit as st
import sqlite3
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import os

st.set_page_config(
    page_title="Material Request - Purchaser Portal",
    page_icon="🛒",
    layout="wide"
)

st.markdown("""
<style>
    .main-header { font-size: 2.2rem; color: #E94F37; text-align: center; margin-bottom: 1rem; }
    .status-submitted { background: #fff3cd; color: #856404; padding: 4px 10px; border-radius: 12px; }
    .status-approved { background: #d4edda; color: #155724; padding: 4px 10px; border-radius: 12px; }
    .status-ordered { background: #cce5ff; color: #004085; padding: 4px 10px; border-radius: 12px; }
    .status-shipped { background: #d1ecf1; color: #0c5460; padding: 4px 10px; border-radius: 12px; }
    .status-received { background: #d4edda; color: #155724; padding: 4px 10px; border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "material_requests.db"
UPLOAD_DIR = "uploads"

def get_conn():
    return sqlite3.connect(DB_PATH)

def send_notification(to_email, subject, body, smtp):
    if not smtp.get("user") or not smtp.get("password"):
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp["user"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(smtp.get("server", "smtp.gmail.com"), smtp.get("port", 587))
        server.starttls()
        server.login(smtp["user"], smtp["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Email failed: {e}")
        return False

if "smtp" not in st.session_state:
    st.session_state.smtp = {"server": "smtp.gmail.com", "port": 587, "user": "", "password": "", "cc": ""}

st.sidebar.title("🛒 Purchaser Portal")
st.sidebar.info("Track orders, update statuses, and notify requesters.")
page = st.sidebar.radio("Menu", ["Dashboard & Tracking", "Email Settings"])

if page == "Email Settings":
    st.header("Email Notification Settings")
    st.session_state.smtp["server"] = st.text_input("SMTP Server", st.session_state.smtp["server"])
    st.session_state.smtp["port"] = st.number_input("Port", value=st.session_state.smtp["port"])
    st.session_state.smtp["user"] = st.text_input("From Email", st.session_state.smtp["user"])
    st.session_state.smtp["password"] = st.text_input("App Password", type="password", value=st.session_state.smtp["password"])
    st.session_state.smtp["cc"] = st.text_input("CC / Manager Email (optional)", st.session_state.smtp["cc"])
    st.success("Settings saved for this session.")

elif page == "Dashboard & Tracking":
    st.markdown('<div class="main-header">🛒 Purchaser Dashboard</div>', unsafe_allow_html=True)
    
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT id, requisition_no, project_name, requested_by, requester_email,
               date_required, status, created_at
        FROM requests ORDER BY 
            CASE status 
                WHEN 'Submitted' THEN 1 
                WHEN 'Under Review' THEN 2 
                WHEN 'Approved' THEN 3 
                WHEN 'Ordered' THEN 4 
                ELSE 5 
            END, created_at DESC
    ''', conn)
    conn.close()
    
    if df.empty:
        st.info("No requests yet.")
    else:
        status_options = ["All", "Submitted", "Under Review", "Approved", "Ordered", "Partially Shipped", "Shipped", "Received", "Closed", "Rejected"]
        col1, col2 = st.columns([2,1])
        with col1:
            filt = st.selectbox("Filter by Status", status_options)
        with col2:
            search = st.text_input("Search")
        
        view = df if filt == "All" else df[df["status"] == filt]
        if search:
            view = view[view.apply(lambda r: search.lower() in str(r).lower(), axis=1)]
        
        st.dataframe(view[["requisition_no","project_name","requested_by","date_required","status"]], use_container_width=True, hide_index=True)
        
        if not view.empty:
            sel = st.selectbox("Select request to manage", view["requisition_no"].tolist())
            if sel:
                conn = get_conn()
                req = pd.read_sql_query("SELECT * FROM requests WHERE requisition_no = ?", conn, params=(sel,)).iloc[0]
                items = pd.read_sql_query("SELECT qty, description, code, notes FROM items WHERE request_id = ?", conn, params=(req["id"],))
                docs = pd.read_sql_query("SELECT * FROM documents WHERE request_id = ?", conn, params=(req["id"],))
                hist = pd.read_sql_query("SELECT * FROM status_history WHERE request_id = ? ORDER BY changed_at DESC", conn, params=(req["id"],))
                conn.close()
                
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**{req['requisition_no']}** — {req['project_name']}")
                    st.write(f"Requester: {req['requested_by']} ({req['requester_email']})")
                    st.write(f"Delivery: {req['delivery_address'] or '—'}")
                    st.write(f"Segment: {req['segment'] or '—'}")
                with c2:
                    st.write(f"**Required by:** {req['date_required']}")
                    st.write(f"**Current status:** {req['status']}")
                    st.write(f"Notes: {req['notes'] or '—'}")
                
                st.subheader("Items to Purchase")
                st.dataframe(items, use_container_width=True)
                
                if not docs.empty:
                    st.subheader("Attached Documents")
                    for _, d in docs.iterrows():
                        p = os.path.join(UPLOAD_DIR, d["filename"])
                        if os.path.exists(p):
                            with open(p, "rb") as f:
                                st.download_button(f"{d['original_name']} ({d['doc_type']})", f, file_name=d["original_name"], key=d["filename"])
                
                st.subheader("Update Status")
                new_status = st.selectbox("New Status", 
                    ["Submitted","Under Review","Approved","Ordered","Partially Shipped","Shipped","Received","Closed","Rejected"],
                    index=0)
                update_note = st.text_area("Notes for this update (will be emailed to requester)")
                changed_by = st.text_input("Your name", value="Purchasing")
                
                if st.button("Update Status & Notify Requester", type="primary"):
                    now = datetime.now().isoformat()
                    conn = get_conn()
                    c = conn.cursor()
                    c.execute("UPDATE requests SET status=?, updated_at=? WHERE id=?", (new_status, now, req["id"]))
                    c.execute("INSERT INTO status_history (request_id, status, notes, changed_by, changed_at) VALUES (?,?,?,?,?)",
                              (req["id"], new_status, update_note, changed_by, now))
                    conn.commit()
                    conn.close()
                    
                    subject = f"Material Request {sel} → {new_status}"
                    body = f"""Your material request has been updated.

Requisition: {sel}
Project: {req['project_name']}
New Status: {new_status}
Notes: {update_note or 'None'}
Updated by: {changed_by}

Thank you.
"""
                    sent = send_notification(req["requester_email"], subject, body, st.session_state.smtp)
                    if st.session_state.smtp.get("cc"):
                        send_notification(st.session_state.smtp["cc"], subject, body, st.session_state.smtp)
                    st.success("Status updated!" + (" Email sent." if sent else " (Email not configured)"))
                    st.rerun()
                
                with st.expander("Status History"):
                    st.dataframe(hist[["status","notes","changed_by","changed_at"]])

st.sidebar.markdown("---")
st.sidebar.caption("Purchaser version – track & update statuses")
