import os
import sqlite3
import uuid
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Material Requests", layout="wide")

DB_PATH = "material_requests.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
PURCHASE_EMAIL = "Sarah.sharearm@thecomfortgroup.com"

STATUSES = [
    "Submitted", "Under Review", "Approved", "Ordered",
    "Partially Shipped", "Shipped", "Received", "Closed", "Rejected",
]


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            number TEXT
        )"""
    )
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
            description TEXT,
            code TEXT,
            notes TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            filename TEXT,
            original_name TEXT,
            doc_type TEXT,
            uploaded_at TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER,
            status TEXT,
            notes TEXT,
            changed_by TEXT,
            changed_at TEXT
        )"""
    )
    conn.commit()
    conn.close()


init_db()


def load_projects():
    conn = get_conn()
    rows = conn.execute("SELECT name, number FROM projects ORDER BY name").fetchall()
    conn.close()
    return rows


def add_project(name, number):
    name = (name or "").strip()
    number = (number or "").strip()
    if not name:
        return False
    conn = get_conn()
    conn.execute(
        "INSERT INTO projects (name, number) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET number=excluded.number",
        (name, number),
    )
    conn.commit()
    conn.close()
    return True


def generate_requisition_no():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM requests")
    count = c.fetchone()[0] + 1
    conn.close()
    return f"MR-{datetime.now().strftime('%Y%m%d')}-{count:04d}"


def send_notification(to_email, subject, body, smtp):
    if not to_email or not smtp.get("user") or not smtp.get("password"):
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = smtp["user"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(smtp.get("server", "smtp.gmail.com"), int(smtp.get("port", 587)))
        server.starttls()
        server.login(smtp["user"], smtp["password"])
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Email failed: {e}")
        return False


def load_requests():
    conn = get_conn()
    df = pd.read_sql_query(
        """
        SELECT id, requisition_no, project_name, project_number, requested_by,
               requester_email, date_required, status, created_at
        FROM requests
        ORDER BY
            CASE status
                WHEN 'Submitted' THEN 1
                WHEN 'Under Review' THEN 2
                WHEN 'Approved' THEN 3
                WHEN 'Ordered' THEN 4
                ELSE 5
            END, created_at DESC
        """,
        conn,
    )
    conn.close()
    return df


if "smtp" not in st.session_state:
    st.session_state.smtp = {
        "server": "smtp.gmail.com",
        "port": 587,
        "user": "",
        "password": "",
        "purchase_email": PURCHASE_EMAIL,
    }

st.sidebar.title("Material requests")
page = st.sidebar.radio(
    "Menu",
    ["Request supplies", "Track orders", "Projects", "Email settings"],
)

if page == "Projects":
    st.header("Projects")
    st.caption("Add each project once. The request form and the tracker both use this list.")
    with st.form("add_project"):
        c1, c2 = st.columns(2)
        with c1:
            new_name = st.text_input("Project name")
        with c2:
            new_number = st.text_input("Project number")
        if st.form_submit_button("Save project"):
            if add_project(new_name, new_number):
                st.success("Saved.")
                st.rerun()
            else:
                st.error("Project name is required.")
    projects = load_projects()
    if projects:
        st.dataframe(
            pd.DataFrame(projects, columns=["Project name", "Project number"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No projects yet.")

elif page == "Email settings":
    st.header("Email notifications")
    st.caption("Enter the Gmail that sends the mail, and a Gmail app password.")
    st.session_state.smtp["server"] = st.text_input("SMTP server", st.session_state.smtp["server"])
    st.session_state.smtp["port"] = st.number_input("Port", value=int(st.session_state.smtp["port"]))
    st.session_state.smtp["user"] = st.text_input("From email", st.session_state.smtp["user"])
    st.session_state.smtp["password"] = st.text_input(
        "App password", type="password", value=st.session_state.smtp["password"]
    )
    st.session_state.smtp["purchase_email"] = st.text_input(
        "Purchase email (receives new requests)",
        st.session_state.smtp.get("purchase_email", PURCHASE_EMAIL),
    )
    st.success("Saved for this session.")

elif page == "Request supplies":
    st.header("Request supplies")
    projects = load_projects()
    project_names = [p[0] for p in projects]
    project_map = {p[0]: p[1] for p in projects}
    with st.form("request_form"):
        col1, col2 = st.columns(2)
        with col1:
            if project_names:
                project_name = st.selectbox("Project name *", project_names)
                project_number = project_map.get(project_name, "")
                st.text_input("Project number", value=project_number, disabled=True)
            else:
                st.warning("Add projects under Projects in the menu first.")
                project_name = ""
                project_number = ""
            segment = st.text_input("Segment / trade")
            requested_by = st.text_input("Requested by *")
            requester_email = st.text_input("Your email *")
        with col2:
            delivery_address = st.text_area("Delivery address")
            date_ordered = st.date_input("Date ordered", value=date.today())
            date_required = st.date_input("Date required")
            notes = st.text_area("Notes")
        st.subheader("Line items")
        items_df = st.data_editor(
            pd.DataFrame({"Qty": [1.0], "Description": [""], "Code / SKU": [""], "Notes": [""]}),
            num_rows="dynamic",
            use_container_width=True,
        )
        uploaded_files = st.file_uploader(
            "Attach a quote, spec, photo, or SDS",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx"],
        )
        submitted = st.form_submit_button("Submit request", type="primary")
    if submitted:
        if not (project_name and requested_by and requester_email):
            st.error("Project, requested by, and email are required.")
        else:
            req_no = generate_requisition_no()
            now = datetime.now().isoformat()
            conn = get_conn()
            c = conn.cursor()
            c.execute(
                """INSERT INTO requests
                   (requisition_no, project_name, project_number, delivery_address, segment,
                    requested_by, requester_email, date_ordered, date_required, notes,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    req_no, project_name, project_number, delivery_address, segment,
                    requested_by, requester_email, str(date_ordered), str(date_required),
                    notes, now, now,
                ),
            )
            rid = c.lastrowid
            lines = []
            for _, row in items_df.iterrows():
                if str(row.get("Description") or "").strip():
                    c.execute(
                        "INSERT INTO items (request_id, qty, description, code, notes) VALUES (?,?,?,?,?)",
                        (rid, row["Qty"], row["Description"], row["Code / SKU"], row["Notes"]),
                    )
                    lines.append(
                        f"- {row['Qty']} x {row['Description']} ({row['Code / SKU'] or 'no code'})"
                    )
            if uploaded_files:
                for f in uploaded_files:
                    fid = str(uuid.uuid4())
                    fname = f"{fid}{os.path.splitext(f.name)[1]}"
                    with open(os.path.join(UPLOAD_DIR, fname), "wb") as out:
                        out.write(f.getbuffer())
                    c.execute(
                        "INSERT INTO documents (request_id, filename, original_name, doc_type, uploaded_at) VALUES (?,?,?,?,?)",
                        (rid, fname, f.name, "Attachment", now),
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
            sent = send_notification(purchase_to, subject, body, st.session_state.smtp)
            if sent:
                st.success(f"Request {req_no} submitted. Email sent to {purchase_to}.")
            else:
                st.success(f"Request {req_no} is on the order list.")
                st.warning("Purchase email was not sent. Open Email settings and enter the from address and app password.")

else:
    st.header("Track orders")
    df = load_requests()
    if df.empty:
        st.info("No requests yet. Use Request supplies in the menu to add one.")
    else:
        names = ["All"] + sorted({x for x in df["project_name"].dropna().tolist() if x})
        numbers = ["All"] + sorted({x for x in df["project_number"].dropna().tolist() if x})
        f1, f2, f3 = st.columns(3)
        with f1:
            name_filt = st.selectbox("Project name", names)
        with f2:
            number_filt = st.selectbox("Project number", numbers)
        with f3:
            filt = st.selectbox("Status", ["All"] + STATUSES)
        search = st.text_input("Search")
        view = df
        if name_filt != "All":
            view = view[view["project_name"] == name_filt]
        if number_filt != "All":
            view = view[view["project_number"] == number_filt]
        if filt != "All":
            view = view[view["status"] == filt]
        if search:
            view = view[view.apply(lambda r: search.lower() in str(r).lower(), axis=1)]
        st.dataframe(
            view[["requisition_no", "project_name", "project_number", "requested_by", "date_required", "status"]],
            use_container_width=True,
            hide_index=True,
        )
        if view.empty:
            st.caption("Nothing matches that filter.")
        else:
            sel = st.selectbox("Open a request", view["requisition_no"].tolist())
            conn = get_conn()
            req = pd.read_sql_query(
                "SELECT * FROM requests WHERE requisition_no = ?", conn, params=(sel,)
            ).iloc[0]
            items = pd.read_sql_query(
                "SELECT qty, description, code, notes FROM items WHERE request_id = ?",
                conn, params=(int(req["id"]),),
            )
            docs = pd.read_sql_query(
                "SELECT * FROM documents WHERE request_id = ?",
                conn, params=(int(req["id"]),),
            )
            hist = pd.read_sql_query(
                "SELECT status, notes, changed_by, changed_at FROM status_history WHERE request_id = ? ORDER BY changed_at DESC",
                conn, params=(int(req["id"]),),
            )
            conn.close()
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**{req['requisition_no']}** - {req['project_name']}")
                st.write(f"Project number: {req['project_number'] or '-'}")
                st.write(f"Requester: {req['requested_by']} ({req['requester_email']})")
                st.write(f"Delivery: {req['delivery_address'] or '-'}")
                st.write(f"Segment: {req['segment'] or '-'}")
            with c2:
                st.write(f"**Required by:** {req['date_required']}")
                st.write(f"**Status:** {req['status']}")
                st.write(f"Notes: {req['notes'] or '-'}")
            st.subheader("Items")
            st.dataframe(items, use_container_width=True)
            if not docs.empty:
                st.subheader("Attachments")
                for _, d in docs.iterrows():
                    path = os.path.join(UPLOAD_DIR, d["filename"])
                    if os.path.exists(path):
                        with open(path, "rb") as f:
                            st.download_button(d["original_name"], f, file_name=d["original_name"], key=d["filename"])
            st.subheader("Update status")
            current = req["status"] if req["status"] in STATUSES else "Submitted"
            new_status = st.selectbox("New status", STATUSES, index=STATUSES.index(current))
            update_note = st.text_area("Note for the requester")
            changed_by = st.text_input("Updated by", value="Purchasing")
            if st.button("Save status", type="primary"):
                now = datetime.now().isoformat()
                conn = get_conn()
                c = conn.cursor()
                c.execute(
                    "UPDATE requests SET status=?, updated_at=? WHERE id=?",
                    (new_status, now, int(req["id"])),
                )
                c.execute(
                    "INSERT INTO status_history (request_id, status, notes, changed_by, changed_at) VALUES (?,?,?,?,?)",
                    (int(req["id"]), new_status, update_note, changed_by, now),
                )
                conn.commit()
                conn.close()
                subject = f"Material request {sel} is now {new_status}"
                body = (
                    f"Requisition: {sel}\n"
                    f"Project: {req['project_name']}\n"
                    f"New status: {new_status}\n"
                    f"Notes: {update_note or 'None'}\n"
                    f"Updated by: {changed_by}\n"
                )
                sent = send_notification(req["requester_email"], subject, body, st.session_state.smtp)
                st.success("Status saved." + (" Email sent." if sent else " Email is not set up."))
                st.rerun()
            with st.expander("Status history"):
                st.dataframe(hist, use_container_width=True)
