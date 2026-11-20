import os
import sqlite3
import uuid
import smtplib
import ssl
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Material Request - Requester Portal",
    page_icon=":memo:",
    layout="wide",
)

st.markdown(
    """
<style>
    .main-header { font-size: 2.2rem; color: #2E86AB; text-align: center; margin-bottom: 1rem; }
    .info-box { background-color: #f0f8ff; padding: 1rem; border-radius: 0.5rem; border-left: 4px solid #2E86AB; }
</style>
""",
    unsafe_allow_html=True,
)

DB_PATH = "material_requests.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
PURCHASE_EMAIL = "Sarah.sharearm@thecomfortgroup.com"
UNITS = ["Each", "ft", "sf", "rolls", "box", "bag", "lb", "gal", "sheet", "other"]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        requisition_no TEXT UNIQUE,
        project_name TEXT,
        project_number TEXT,
        delivery_address TEXT,
        segment TEXT,
        requested_by TEXT,
        requester_email TEXT,
        date_ordered TEXT,
        date_required TEXT,
        status TEXT DEFAULT 'Submitted',
        notes TEXT,
        created_at TEXT,
        updated_at TEXT
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER,
        qty REAL,
        uom TEXT,
        description TEXT,
        code TEXT,
        notes TEXT,
        FOREIGN KEY (request_id) REFERENCES requests(id)
    )"""
    )
    try:
        c.execute("ALTER TABLE items ADD COLUMN uom TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute(
        """CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER,
        filename TEXT,
        original_name TEXT,
        doc_type TEXT,
        uploaded_at TEXT,
        FOREIGN KEY (request_id) REFERENCES requests(id)
    )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER,
        status TEXT,
        notes TEXT,
        changed_by TEXT,
        changed_at TEXT,
        FOREIGN KEY (request_id) REFERENCES requests(id)
    )"""
    )
    conn.commit()
    conn.close()


init_db()


def get_conn():
    return sqlite3.connect(DB_PATH)


def generate_requisition_no():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM requests")
    count = c.fetchone()[0] + 1
    conn.close()
    return f"MR-{datetime.now().strftime('%Y%m%d')}-{count:04d}"


def send_notification(to_email, subject, body, smtp):
    user = (smtp.get("user") or "").strip()
    password = (smtp.get("password") or "").replace(" ", "")
    host = (smtp.get("server") or "smtp.office365.com").strip()
    if not to_email or not user or not password:
        return False, "From email and password are blank."
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    context = ssl.create_default_context()
    errors = []
    attempts = [(587, "starttls"), (465, "ssl")]
    if "gmail" in host:
        attempts = [(465, "ssl"), (587, "starttls")]
    for port, mode in attempts:
        try:
            if mode == "ssl":
                with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
                    server.login(user, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(user, password)
                    server.send_message(msg)
            return True, ""
        except Exception as e:
            errors.append(f"{port}: {e}")
    return False, " | ".join(errors)


if "smtp" not in st.session_state:
    st.session_state.smtp = {
        "server": "smtp.office365.com",
        "port": 587,
        "user": "",
        "password": "",
        "purchase_email": PURCHASE_EMAIL,
    }

st.sidebar.title("Requester Portal")
st.sidebar.info("Submit a request. Purchasing gets an email when you submit.")
page = st.sidebar.radio("Menu", ["Submit New Request", "My Requests", "Email settings"])

if page == "Email settings":
    st.header("Email settings")
    st.caption("This is the mailbox that sends the notice. Sarah's address is who receives it.")
    st.session_state.smtp["server"] = st.text_input("SMTP server", st.session_state.smtp["server"])
    st.session_state.smtp["port"] = st.number_input("Port", value=int(st.session_state.smtp["port"]))
    st.session_state.smtp["user"] = st.text_input("From email (your Comfort Group email)", st.session_state.smtp["user"])
    st.session_state.smtp["password"] = st.text_input(
        "Mailbox password", type="password", value=st.session_state.smtp["password"]
    )
    st.session_state.smtp["purchase_email"] = st.text_input(
        "Purchase email", st.session_state.smtp.get("purchase_email", PURCHASE_EMAIL)
    )
    st.info("Comfort Group uses Outlook. Server must be smtp.office365.com, port 587. Use your normal work password, or an app password if IT requires one.")
    if st.button("Send a test email"):
        ok, err = send_notification(
            st.session_state.smtp.get("purchase_email") or PURCHASE_EMAIL,
            "Material request test",
            "This is a test from the material request app.",
            st.session_state.smtp,
        )
        if ok:
            st.success("Test email sent.")
        else:
            st.error(err)

elif page == "Submit New Request":
    st.markdown('<div class="main-header">Submit Material Request</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="info-box">Fill out the form below. A copy is emailed to purchasing when Email settings are filled in.</div>',
        unsafe_allow_html=True,
    )

    with st.form("request_form"):
        col1, col2 = st.columns(2)
        with col1:
            project_name = st.text_input("Project Name *")
            project_number = st.text_input("Project Number")
            segment = st.text_input("Segment / Trade")
            requested_by = st.text_input("Requested By *")
            requester_email = st.text_input("Your Email *")
        with col2:
            delivery_address = st.text_area("Delivery Address")
            date_ordered = st.date_input("Date Ordered", value=date.today())
            date_required = st.date_input("Date Required")
            notes = st.text_area("Special Instructions / Notes")

        st.subheader("Line Items")
        items_df = st.data_editor(
            pd.DataFrame({"Qty": [1.0], "UOM": ["Each"], "Description": [""], "Code / SKU": [""], "Notes": [""]}),
            column_config={
                "UOM": st.column_config.SelectboxColumn("UOM", options=UNITS, required=True),
            },
            num_rows="dynamic",
            use_container_width=True,
        )

        st.subheader("Attach Documents")
        st.caption("Common: Vendor quotes, specs, drawings, photos of existing materials, SDS, etc.")
        uploaded_files = st.file_uploader(
            "Upload files",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"],
        )

        doc_types = []
        if uploaded_files:
            for f in uploaded_files:
                dtype = st.selectbox(
                    f"Document type for {f.name}",
                    ["Vendor Quote", "Drawing/Spec", "Photo", "SDS", "Other"],
                    key=f.name,
                )
                doc_types.append(dtype)

        if st.form_submit_button("Submit Request", type="primary"):
            if not (project_name and requested_by and requester_email):
                st.error("Project Name, Requested By, and Email are required.")
            else:
                req_no = generate_requisition_no()
                now = datetime.now().isoformat()
                conn = get_conn()
                c = conn.cursor()
                c.execute(
                    """INSERT INTO requests
                    (requisition_no, project_name, project_number, delivery_address, segment,
                     requested_by, requester_email, date_ordered, date_required, notes, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        req_no,
                        project_name,
                        project_number,
                        delivery_address,
                        segment,
                        requested_by,
                        requester_email,
                        str(date_ordered),
                        str(date_required),
                        notes,
                        now,
                        now,
                    ),
                )
                rid = c.lastrowid
                lines = []
                for _, row in items_df.iterrows():
                    if row.get("Description"):
                        c.execute(
                            "INSERT INTO items (request_id, qty, uom, description, code, notes) VALUES (?,?,?,?,?,?)",
                            (rid, row["Qty"], row.get("UOM") or "Each", row["Description"], row["Code / SKU"], row["Notes"]),
                        )
                        lines.append(
                            f"- {row['Qty']} {row.get('UOM') or 'Each'} {row['Description']} ({row['Code / SKU'] or 'no code'})"
                        )
                if uploaded_files:
                    for i, f in enumerate(uploaded_files):
                        fid = str(uuid.uuid4())
                        fname = f"{fid}{os.path.splitext(f.name)[1]}"
                        with open(os.path.join(UPLOAD_DIR, fname), "wb") as out:
                            out.write(f.getbuffer())
                        c.execute(
                            "INSERT INTO documents (request_id, filename, original_name, doc_type, uploaded_at) VALUES (?,?,?,?,?)",
                            (rid, fname, f.name, doc_types[i], now),
                        )
                c.execute(
                    "INSERT INTO status_history (request_id, status, notes, changed_by, changed_at) VALUES (?,?,?,?,?)",
                    (rid, "Submitted", "New request", requested_by, now),
                )
                conn.commit()
                conn.close()

                subject = f"New material request {req_no}"
                body = (
                    f"A new material request was submitted.\n\n"
                    f"Requisition: {req_no}\n"
                    f"Project: {project_name}\n"
                    f"Project number: {project_number or '-'}\n"
                    f"Segment: {segment or '-'}\n"
                    f"Requested by: {requested_by} ({requester_email})\n"
                    f"Delivery: {delivery_address or '-'}\n"
                    f"Date required: {date_required}\n"
                    f"Notes: {notes or '-'}\n\n"
                    f"Items:\n"
                    + ("\n".join(lines) if lines else "- None listed")
                )
                purchase_to = st.session_state.smtp.get("purchase_email") or PURCHASE_EMAIL
                sent, err = send_notification(purchase_to, subject, body, st.session_state.smtp)
                st.success(f"Request {req_no} submitted. You can track it under My Requests.")
                if sent:
                    st.success(f"Email sent to {purchase_to}.")
                else:
                    st.warning(f"Purchase email was not sent. {err} Open Email settings on the left.")

elif page == "My Requests":
    st.markdown('<div class="main-header">My Material Requests</div>', unsafe_allow_html=True)
    email = st.text_input("Enter your email to view your requests", placeholder="you@company.com")
    if email:
        conn = get_conn()
        df = pd.read_sql_query(
            "SELECT requisition_no, project_name, date_required, status, created_at FROM requests WHERE requester_email = ? ORDER BY created_at DESC",
            conn,
            params=(email,),
        )
        conn.close()
        if df.empty:
            st.info("No requests found for this email.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            selected = st.selectbox("View details", df["requisition_no"].tolist())
            if selected:
                conn = get_conn()
                req = pd.read_sql_query(
                    "SELECT * FROM requests WHERE requisition_no = ?", conn, params=(selected,)
                ).iloc[0]
                items = pd.read_sql_query(
                    "SELECT qty, uom, description, code, notes FROM items WHERE request_id = ?",
                    conn,
                    params=(req["id"],),
                )
                docs = pd.read_sql_query(
                    "SELECT original_name, doc_type, filename FROM documents WHERE request_id = ?",
                    conn,
                    params=(req["id"],),
                )
                hist = pd.read_sql_query(
                    "SELECT status, notes, changed_by, changed_at FROM status_history WHERE request_id = ? ORDER BY changed_at",
                    conn,
                    params=(req["id"],),
                )
                conn.close()
                st.write(f"**Status:** {req['status']}")
                st.write(f"**Project:** {req['project_name']} | **Required:** {req['date_required']}")
                st.subheader("Items")
                st.dataframe(items)
                if not docs.empty:
                    st.subheader("Your Attachments")
                    for _, d in docs.iterrows():
                        path = os.path.join(UPLOAD_DIR, d["filename"])
                        if os.path.exists(path):
                            with open(path, "rb") as f:
                                st.download_button(d["original_name"], f, file_name=d["original_name"])
                st.subheader("Status History")
                st.dataframe(hist)

st.sidebar.markdown("---")
st.sidebar.caption("Requester version")
