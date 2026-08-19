import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import datetime
import base64
import random
import string
import re
import os
import tempfile
import io

from pypdf import PdfReader, PdfWriter
try:
    from weasyprint import HTML
    PDF_ENGINE_AVAILABLE = True
except Exception as e:
    PDF_ENGINE_AVAILABLE = False

try:
    from google import genai
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# --- 1. CONFIGURATION & DATABASE AUTO-MIGRATION ---
st.set_page_config(
    page_title="Springnexa Enterprise HMIS | Clinical Suite",
    layout="wide",
    page_icon="🏥",
    initial_sidebar_state="collapsed"
)

DB_FILE = "clinic_records.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            study_date TEXT NOT NULL,
            age_gender TEXT,
            address TEXT,
            ref_physician TEXT,
            rep_physician TEXT,
            technician TEXT,
            doc_kind TEXT NOT NULL,
            sampled_nerves TEXT,
            motor_findings TEXT,
            sensory_findings TEXT,
            f_waves TEXT,
            bg_activity TEXT,
            epi_activity TEXT,
            activation TEXT,
            artifacts TEXT,
            impression TEXT,
            tech_summary TEXT,
            graph_data TEXT,
            graph_type TEXT,
            summary_data TEXT,
            summary_type TEXT,
            billing_amount REAL DEFAULT 1500.0,
            payment_status TEXT DEFAULT 'Unpaid',
            status TEXT NOT NULL DEFAULT 'Pending Doctor Review',
            generation_date TEXT,
            despatch_date TEXT,
            is_archived INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    for col_def in [
        ("billing_amount", "REAL DEFAULT 1500.0"),
        ("payment_status", "TEXT DEFAULT 'Unpaid'"),
        ("graph_data", "TEXT"), ("graph_type", "TEXT"),
        ("summary_data", "TEXT"), ("summary_type", "TEXT"),
        ("sampled_nerves", "TEXT"), ("motor_findings", "TEXT"), ("sensory_findings", "TEXT"),
        ("f_waves", "TEXT"), ("bg_activity", "TEXT"), ("epi_activity", "TEXT"),
        ("activation", "TEXT"), ("impression", "TEXT"), ("tech_summary", "TEXT"),
        ("generation_date", "TEXT"), ("despatch_date", "TEXT"),
        ("is_archived", "INTEGER DEFAULT 0")
    ]:
        try:
            cursor.execute(f"ALTER TABLE patients ADD COLUMN {col_def[0]} {col_def[1]}")
        except:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portal_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email_or_phone TEXT NOT NULL,
            role TEXT NOT NULL,
            access_pin TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'APPROVED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portal_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO portal_settings VALUES ('clinic_name', 'AL-JAWAHIRA ELECTROPHYSIOLOGY')")
    cursor.execute("INSERT OR IGNORE INTO portal_settings VALUES ('sub_header', 'CENTER FOR ADVANCED NEURO DIAGNOSTICS')")
    cursor.execute("INSERT OR IGNORE INTO portal_settings VALUES ('logo_b64', '')")
    cursor.execute("INSERT OR IGNORE INTO portal_settings VALUES ('ai_api_key', '')")
    
    cursor.execute("SELECT COUNT(*) FROM portal_users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ('Master Administrator', 'admin@springnexa.in', 'Admin', 'springnexa2026', 'APPROVED'),
            ('Senior Technician', '+91-7006318286', 'Technician', '7006', 'APPROVED'),
            ('Consultant Neurologist', 'doctor@springnexa.in', 'Doctor', 'ajep786', 'APPROVED')
        ]
        cursor.executemany("""
            INSERT INTO portal_users (full_name, email_or_phone, role, access_pin, status)
            VALUES (?, ?, ?, ?, ?)
        """, default_users)
        
    conn.commit()
    conn.close()

init_db()

def get_settings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM portal_settings")
    rows = cur.fetchall()
    conn.close()
    return {r['setting_key']: r['setting_value'] for r in rows}

# --- 2. SECURE PDF DOCUMENT ENGINE ---
def generate_pdf(html_content, password=None):
    if not PDF_ENGINE_AVAILABLE:
        return None, "WeasyPrint PDF engine missing system libraries (GTK3)."
    try:
        pdf_bytes = HTML(string=html_content).write_pdf()
        if password:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(password)
            output = io.BytesIO()
            writer.write(output)
            return output.getvalue(), None
        return pdf_bytes, None
    except Exception as e:
        return None, str(e)

def generate_code39_svg(data):
    code39 = {
        '1':'100100001','2':'001100001','3':'101100000','4':'000110001','5':'100110000',
        '6':'001110000','7':'000100101','8':'100100100','9':'001100100','0':'000110100',
        'A':'100001001','B':'001001001','C':'101001000','D':'000011001','E':'100011000',
        'F':'001011000','G':'000001101','H':'100001100','I':'001001100','J':'000011100',
        'K':'100000011','L':'001000011','M':'101000010','N':'000010011','O':'100010010',
        'P':'001010010','Q':'000000111','R':'100000110','S':'001000110','T':'000010110',
        'U':'110000001','V':'011000001','W':'111000000','X':'010010001','Y':'110010000',
        'Z':'011010000','-':'010000101','.':'110000100',' ':'011000100','*':'010010100'
    }
    data = f"*{str(data).upper().strip()}*"
    svg_elements = []
    x = 0
    for char in data:
        if char not in code39: continue
        pattern = code39[char]
        for i, bit in enumerate(pattern):
            width = 3 if bit == '1' else 1.5
            if i % 2 == 0:
                svg_elements.append(f'<rect x="{x}" y="0" width="{width}" height="26" fill="#071952" />')
            x += width
        x += 1.5
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="26" viewBox="0 0 {x} 26" preserveAspectRatio="none">{"".join(svg_elements)}</svg>'

def build_report_html(p):
    p = dict(p)
    settings = get_settings()
    c_name = settings.get('clinic_name', 'AL-JAWAHIRA ELECTROPHYSIOLOGY')
    c_sub = settings.get('sub_header', 'CENTER FOR ADVANCED NEURO DIAGNOSTICS')
    c_logo = settings.get('logo_b64', '')
    
    logo_html = f'<img src="{c_logo}" style="max-height:65px; margin-bottom:4px;">' if c_logo else ''
    doc_id_clean = str(p.get('patient_id', 'N/A')).split('/')[0].strip()
    barcode_svg = generate_code39_svg(f"BARCODE-{doc_id_clean}")
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=90x90&data=https://repncs.springnexa.in/download?id={doc_id_clean}"
    
    rep_phys = str(p.get('rep_physician', ''))
    is_rayees = "Rayees" in rep_phys
    doc_name = "Dr Rayees Ahmad Tarray" if is_rayees else "Dr. Aadil Majeed"
    doc_deg2 = "DM Neurology (SKIMS Soura)" if is_rayees else "DrNB Neurology"
    tech_name = p.get('technician') or "Mr Murtaza Amin"
    gen_date = p.get('generation_date') or datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    des_date = p.get('despatch_date') or datetime.datetime.now().strftime("%d-%m-%Y")

    graph_section = ""
    if p.get('graph_data'):
        if 'application/pdf' in str(p.get('graph_type', '')):
            graph_section = f"""
            <div style="page-break-before: always; margin-top:20px;">
                <div style="font-family:'Plus Jakarta Sans'; font-size:9pt; font-weight:800; color:#071952; border-bottom:1.5px solid #cbd5e1; margin-bottom:10px; text-transform:uppercase;">
                    Attached Clinical Trace / PDF Document
                </div>
                <p style="font-size:8.5pt; color:#64748b; font-style:italic;">[Embedded PDF Document Attached by Technician]</p>
            </div>
            """
        else:
            graph_section = f"""
            <div style="page-break-before: always; margin-top:20px;">
                <div style="font-family:'Plus Jakarta Sans'; font-size:9pt; font-weight:800; color:#071952; border-bottom:1.5px solid #cbd5e1; margin-bottom:10px; text-transform:uppercase;">
                    Attached Clinical Trace / Machine Graph
                </div>
                <div style="text-align:center;">
                    <img src="{p.get('graph_data')}" style="max-width:100%; max-height:750px; border:1px solid #cbd5e1; padding:4px;">
                </div>
            </div>
            """

    if p.get('doc_kind') == 'Front Cover Page':
        return f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
            @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800;900&family=Cinzel:wght@700&display=swap');
            @page {{ size: A4; margin: 5mm 8mm; }} @media print {{ body {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }} }}
            body {{ font-family: 'Plus Jakarta Sans', sans-serif; margin: 0; padding: 6px 12px; color: #0f172a; font-size: 10pt; line-height: 1.25; }}
            .facility-bar {{ display: flex; justify-content: space-between; font-size: 8.5pt; font-weight: 700; font-style: italic; color: #334155; border-bottom: 1.5px solid #000; padding-bottom: 2px; }}
            .contact-bar {{ text-align: center; font-size: 13pt; font-weight: 800; color: #071952; margin-top: 6px; }}
            .main-heading {{ text-align: center; font-family: 'Cinzel', serif; font-size: 24pt; font-weight: 900; color: #071952; margin: 2px 0; }}
            .sub-heading {{ text-align: center; font-size: 14pt; font-weight: 800; color: #b91c1c; text-transform: uppercase; margin: 0; }}
            .dossier-box {{ border: 2px solid #071952; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
            .dossier-header {{ background: #071952; color: #ffffff; font-weight: 900; text-align: center; font-size: 10.5pt; padding: 4px 0; text-transform: uppercase; }}
            .dossier-table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
            .dossier-table td {{ padding: 3.5px 8px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; }}
            .d-lbl {{ font-weight: 900; color: #334155; width: 20%; text-transform: uppercase; }}
            .d-val {{ font-weight: 700; color: #0f172a; width: 30%; }}
        </style></head><body>
            <div class="facility-bar"><span>Facility ID: IN0110011072</span><span>S&E Act Reg No: 8172196683</span></div>
            <div class="contact-bar">+91-7006318286 | +91-6006220236</div>
            <div style="text-align:center;">{logo_html}</div>
            <div class="main-heading">E-SUSHRUT CLINIC</div><div class="sub-heading">{c_name}</div>
            <div class="dossier-box">
                <table class="dossier-table">
                    <tr><td colspan="4" class="dossier-header">PATIENT INFORMATION</td></tr>
                    <tr><td class="d-lbl">ID / REF.NO.</td><td class="d-val">{p.get('patient_id')}</td><td class="d-lbl">DATE</td><td class="d-val">{p.get('study_date')}</td></tr>
                    <tr><td class="d-lbl">NAME</td><td class="d-val">{p.get('patient_name')}</td><td class="d-lbl">REF.PHYSICIAN</td><td class="d-val">{p.get('ref_physician')}</td></tr>
                    <tr><td class="d-lbl">AGE / SEX</td><td class="d-val">{p.get('age_gender')}</td><td class="d-lbl">PHYSICIAN</td><td class="d-val">{doc_name}</td></tr>
                    <tr><td class="d-lbl">HT. / WT.</td><td class="d-val"> / </td><td class="d-lbl">TECHNICIAN</td><td class="d-val">{tech_name}</td></tr>
                    <tr><td class="d-lbl">ADDRESS</td><td class="d-val">{p.get('address')}</td><td class="d-lbl">DIAGNOSIS</td><td class="d-val"></td></tr>
                </table>
            </div>
            {graph_section}
        </body></html>
        """
    else:
        doc_header = "NERVE CONDUCTION STUDIES REPORT" if p.get('doc_kind') == 'NCS Report' else "DIGITAL ELECTROENCEPHALOGRAM (EEG) REPORT"
        
        if p.get('doc_kind') == 'NCS Report':
            body_section = f"""
            <div style="text-align:center; font-size:11.5pt; font-weight:900; color:#071952; text-decoration:underline; margin: 12px 0;">
                {doc_header}
            </div>
            
            <div style="margin-bottom:8px;">
                <div style="font-size:9.5pt; font-weight:800; color:#071952; text-decoration:underline; margin-bottom:3px;">Nerves Sampled</div>
                <div style="font-size:8.5pt; white-space: pre-wrap;">{p.get('sampled_nerves')}</div>
            </div>
            
            <div style="margin-bottom:10px;">
                <div style="font-size:9pt; font-weight:800; color:#071952; margin-top:6px;">Motor:</div>
                <div style="font-size:8.5pt; white-space: pre-wrap; padding-left: 12px;">{p.get('motor_findings')}</div>
                
                <div style="font-size:9.5pt; font-weight:800; color:#071952; margin-top:6px;">Sensory:</div>
                <div style="font-size:8.5pt; white-space: pre-wrap; padding-left: 12px;">{p.get('sensory_findings')}</div>
                
                <div style="font-size:9pt; font-weight:800; color:#071952; margin-top:6px;">F Waves:</div>
                <div style="font-size:8.5pt; white-space: pre-wrap; padding-left: 12px;">{p.get('f_waves')}</div>
            </div>
            """
        else:
            body_section = f"""
            <div style="text-align:center; font-size:11.5pt; font-weight:900; color:#071952; text-decoration:underline; margin: 12px 0;">
                {doc_header}
            </div>
            <div style="margin-bottom:10px;">
                <div style="font-size:9.5pt; font-weight:800; color:#071952; text-decoration:underline; margin-bottom:3px;">BACKGROUND ACTIVITY</div>
                <div style="font-size:8.5pt; white-space: pre-wrap; padding-left: 12px;">{p.get('bg_activity')}</div>
                
                <div style="font-size:9.5pt; font-weight:800; color:#071952; text-decoration:underline; margin-top:6px; margin-bottom:3px;">EPILEPTIFORM DISCHARGES</div>
                <div style="font-size:8.5pt; white-space: pre-wrap; padding-left: 12px;">{p.get('epi_activity')}</div>
            </div>
            """

        return f"""
        <!DOCTYPE html><html><head><meta charset="UTF-8"><style>
            @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Merriweather:ital,wght@0,300;0,400;0,700&display=swap');
            @page {{ size: A4; margin: 6mm 10mm; }} @media print {{ body {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; background: #ffffff !important; }} }}
            body {{ font-family: 'Merriweather', serif; margin: 0 auto; padding: 6px 10px; color: #0f172a; font-size: 9pt; line-height: 1.2; }}
            .facility-bar {{ display: flex; justify-content: space-between; font-size: 7.5pt; font-weight: 700; font-style: italic; color: #334155; border-bottom: 1.5px solid #000; padding-bottom: 2px; font-family: 'Plus Jakarta Sans', sans-serif; }}
            .contact-bar {{ text-align: center; font-size: 11pt; font-weight: 800; color: #071952; margin-top: 4px; font-family: 'Plus Jakarta Sans', sans-serif; }}
            .brand-title {{ font-family: 'Cinzel', serif; font-size: 18pt; font-weight: 700; color: #071952; text-align: center; margin: 1px 0; }}
            .dossier-box {{ border: 1.5px solid #071952; border-radius: 4px; overflow: hidden; margin-top: 6px; font-family: 'Plus Jakarta Sans', sans-serif; }}
            .dossier-header {{ background: #071952; color: #ffffff; font-weight: 800; text-align: center; font-size: 8.5pt; padding: 2.5px 0; text-transform: uppercase; letter-spacing: 1px; }}
            .dossier-table {{ width: 100%; border-collapse: collapse; font-size: 8pt; }}
            .dossier-table td {{ padding: 2.5px 5px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; }}
            .d-lbl {{ font-weight: 800; color: #334155; width: 18%; text-transform: uppercase; }}
            .d-val {{ font-weight: 700; color: #0f172a; width: 32%; }}
        </style></head><body>
            <div class="facility-bar"><span>Facility ID: IN0110011072</span><span>S&E Act Registration No: 8172196683</span></div>
            <div class="contact-bar">+91-7006318286 &nbsp;|&nbsp; +91-6006220236</div>
            <div style="text-align:center;">{logo_html}</div>
            <div class="brand-title">{c_name}</div>
            <div style="text-align:center; font-family:'Plus Jakarta Sans'; font-size:10.5pt; font-weight:800; color:#b91c1c; text-transform:uppercase;">{c_sub}</div>
            <div style="text-align:center; font-family:'Plus Jakarta Sans'; font-size:7.5pt; font-weight:700; color:#1e293b; text-transform:uppercase; margin-top:1px;">HELLA BUILDING NEAR CHINAR TREE DISTRICT HOSPITAL ROAD KULGAM</div>
            <div style="text-align:center; font-family:'Plus Jakarta Sans'; font-size:6.5pt; font-weight:600; color:#64748b; margin-top:1px; border-top:1px solid #e2e8f0; padding-top:2px;">Operated by SpringNEXA Private Limited • CIN: U86900JK2026PTC018519 | DPIIT Reg: DIPP238776</div>

            <div class="dossier-box">
                <table class="dossier-table">
                    <tr><td colspan="4" class="dossier-header">PATIENT INFORMATION</td></tr>
                    <tr><td class="d-lbl">ID / REF.NO.</td><td class="d-val">{p.get('patient_id')}</td><td class="d-lbl">DATE</td><td class="d-val">{p.get('study_date')}</td></tr>
                    <tr><td class="d-lbl">NAME</td><td class="d-val">{p.get('patient_name')}</td><td class="d-lbl">REF.PHYSICIAN</td><td class="d-val">{p.get('ref_physician')}</td></tr>
                    <tr><td class="d-lbl">AGE / SEX</td><td class="d-val">{p.get('age_gender')}</td><td class="d-lbl">PHYSICIAN</td><td class="d-val">{doc_name}</td></tr>
                    <tr><td class="d-lbl">HT. / WT.</td><td class="d-val"> / </td><td class="d-lbl">TECHNICIAN</td><td class="d-val">{tech_name}</td></tr>
                    <tr><td class="d-lbl">ADDRESS</td><td class="d-val">{p.get('address')}</td><td class="d-lbl">DIAGNOSIS</td><td class="d-val"></td></tr>
                </table>
            </div>

            {body_section}
            
            <div style="margin-bottom:8px; margin-top:10px; font-family:'Plus Jakarta Sans';">
                <span style="font-size:9pt; font-weight:800; color:#071952;">Impression:</span>
                <div style="font-size:9pt; font-weight:800; white-space: pre-wrap; margin-left: 12px; margin-top: 2px; color:#0f172a;">{p.get('impression')}</div>
            </div>

            <div style="text-align:center; font-family:monospace; font-weight:bold; margin-top:15px; font-size: 9pt;">
                ********************End**Of**Report*******************
            </div>
            
            <div style="text-align:center; font-size:8pt; margin-top:4px; font-weight:700; color:#475569; font-family:'Plus Jakarta Sans'; line-height:1.4;">
                This Is Only A Professional Opinion<br>
                Not Valid For Medico-Legal Purposes<br>
                Cutting and overwriting Is not valid<br>
                <span style="font-style:italic; font-weight:400;">Clinical correlation is recommended.</span>
            </div>

            <div style="width:100%; margin-top:12px; border-top:1.5px solid #071952; padding-top:4px; font-family:'Plus Jakarta Sans'; display:flex; justify-content:space-between; align-items:flex-end;">
                <div>
                    <img src="{qr_url}" style="width:50px; height:50px;"><br>
                    <span style="font-size:5pt; font-weight:800;">VERIFY QR</span>
                </div>
                <div style="text-align:center; width: 45%;">
                    <div style="width:100%;">{barcode_svg}</div>
                    <span style="font-family:monospace; font-size:6pt; font-weight:800; color:#071952;">GEN: {gen_date} | DESPATCH: {des_date}</span>
                </div>
                <div style="text-align:right;">
                    <b style="font-size:7pt;">Reported By:</b><br>
                    <span style="font-weight:800;color:#071952;font-size:9pt;">{doc_name}</span><br>
                    <span style="color:#088395;font-size:7pt;font-weight:700;">{doc_deg2}</span>
                </div>
            </div>
            {graph_section}
        </body></html>
        """

# --- 3. AUTHENTICATION GATEWAY ---
if "auth_session" not in st.session_state:
    st.session_state.auth_session = {"logged_in": False, "user": None, "role": None}

def login_user(role, pin_val):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM portal_users WHERE access_pin = ? AND status = 'APPROVED'", (pin_val.strip(),))
    user = cur.fetchone()
    conn.close()
    
    if user:
        if user['role'] != "Admin" and user['role'] != role:
            st.error(f"⚠️ Access Denied: This PIN belongs to a {user['role']}, not a {role}.")
            return False
            
        st.session_state.auth_session = {"logged_in": True, "user": user['full_name'], "role": user['role']}
        st.rerun()
        return True
    else:
        st.error("⚠️ Invalid or unapproved Security Key.")
        return False

def update_patient_status(patient_id, new_status):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE patients SET status = ? WHERE id = ?", (new_status, patient_id))
    conn.commit()
    conn.close()
    st.rerun()

def archive_patient(patient_id, archive_status):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE patients SET is_archived = ? WHERE id = ?", (archive_status, patient_id))
    conn.commit()
    conn.close()
    st.rerun()

# --- UNAUTHENTICATED HOME PAGE ---
if not st.session_state.auth_session["logged_in"]:
    g_settings = get_settings()
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Cinzel:wght@700&display=swap');
        .stApp {{ background: radial-gradient(circle at center, #f8fafc 0%, #cbd5e1 100%); }}
        .login-card {{ max-width: 500px; margin: 40px auto 10px auto; background: #ffffff; border: 1.5px solid #cbd5e1; border-radius: 16px; padding: 30px; box-shadow: 0 20px 40px -10px rgba(7, 25, 82, 0.12); text-align: center; font-family: 'Plus Jakarta Sans', sans-serif; }}
    </style>
    <div class="login-card">
        <div style="font-size:11px;font-weight:800;color:#088395;letter-spacing:1.5px;text-transform:uppercase;">🏥 Enterprise HMIS & EMR Suite</div>
        <h3 style="margin:4px 0;color:#071952;font-family:'Cinzel',serif;font-size:19px;">{g_settings.get('clinic_name', 'AL-JAWAHIRA ELECTROPHYSIOLOGY')}</h3>
        <p style="font-size:12px;color:#64748b;margin-bottom:10px;">Select Your Dedicated Portal</p>
    </div>
    """, unsafe_allow_html=True)

    col_l1, col_l2, col_l3 = st.columns([1, 1.4, 1])
    with col_l2:
        tabs = st.tabs(["📥 Patient", "🔬 Tech", "🩺 Doctor", "👥 Admin"])
        
        with tabs[0]:
            with st.form("patient_search_form"):
                search_query = st.text_input("Patient ID / Phone Number", placeholder="e.g. 1843")
                submitted = st.form_submit_button("🔍 Retrieve Official Report", use_container_width=True)
            
            if submitted and search_query:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("SELECT * FROM patients WHERE patient_id LIKE ? OR patient_name LIKE ? ORDER BY id DESC LIMIT 1", (f"%{search_query.strip()}%", f"%{search_query.strip()}%"))
                match = cur.fetchone()
                conn.close()
                
                if match:
                    if match['status'] == 'Pending Doctor Review' or match['status'] == 'On Hold':
                        st.warning("⚠️ This report is currently pending the Doctor's review and signature.")
                    else:
                        st.success(f"✅ Verified Report Found: **{match['patient_name']}**")
                        html_report = build_report_html(match)
                        
                        with st.expander("👁️ Preview Official Report"):
                            components.html(html_report, height=500, scrolling=True)

                        last_name = match['patient_name'].strip().split()[-1]
                        password = (last_name + match['patient_id']).lower().replace(" ", "")
                        
                        if PDF_ENGINE_AVAILABLE:
                            pdf_bytes, err = generate_pdf(html_report, password)
                            if pdf_bytes:
                                st.download_button(
                                    "📥 Download Password-Protected PDF Report",
                                    data=pdf_bytes,
                                    file_name=f"{match['patient_name']}_Report.pdf",
                                    mime="application/pdf",
                                    use_container_width=True
                                )
                                st.info(f"🔑 **PDF Password:** `{password}` (Your Last Name + ID in lowercase, no spaces)")
                            else:
                                st.error(f"PDF generation error: {err}")
                        else:
                            st.error("⚠️ PDF Engine Unavailable (Missing GTK3 Library on Windows).")
                            st.download_button("📥 Download HTML Fallback Report", data=html_report, file_name=f"{match['patient_name']}_Report.html", mime="text/html", use_container_width=True)
                else:
                    st.error("⚠️ No report found matching that query.")

        with tabs[1]:
            with st.form("tech_login_form"):
                t_pin = st.text_input("Enter Tech PIN", type="password")
                submitted = st.form_submit_button("🔓 Enter Tech Portal", use_container_width=True)
                if submitted:
                    login_user("Technician", t_pin)

        with tabs[2]:
            with st.form("doc_login_form"):
                d_pin = st.text_input("Enter Doctor PIN", type="password")
                submitted = st.form_submit_button("🔓 Enter Doctor Portal", use_container_width=True)
                if submitted:
                    login_user("Doctor", d_pin)
                
        with tabs[3]:
            with st.form("admin_login_form"):
                a_pin = st.text_input("Enter Admin PIN", type="password")
                submitted = st.form_submit_button("🔓 Enter Admin Portal", use_container_width=True)
                if submitted:
                    login_user("Admin", a_pin)
    st.stop()

# --- 4. STRICT ISOLATED USER WORKSPACES ---
current_role = st.session_state.auth_session["role"]
current_user_name = st.session_state.auth_session["user"]
g_settings = get_settings()

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    .stApp { background-color: #f8fafc; font-family: 'Plus Jakarta Sans', sans-serif; }
    .hero-banner { background: linear-gradient(135deg, #071952 0%, #0b2570 50%, #088395 100%); padding: 16px 24px; border-radius: 12px; color: #ffffff; margin-bottom: 20px; box-shadow: 0 10px 25px -5px rgba(7, 25, 82, 0.2); }
</style>
""", unsafe_allow_html=True)

tc1, tc2 = st.columns([5, 1])
with tc1:
    st.markdown(f"""
    <div class="hero-banner">
        <h3 style='margin:0; font-weight:800; font-size:20px;'>{g_settings.get('clinic_name', 'AL-JAWAHIRA ELECTROPHYSIOLOGY')}</h3>
        <p style='margin:2px 0 0 0; font-size:12px; opacity:0.9;'>{g_settings.get('sub_header', 'Enterprise Hospital & Diagnostic Information System')} • Springnexa EMR</p>
    </div>
    """, unsafe_allow_html=True)
with tc2:
    st.markdown(f"<div style='font-size:12px;font-weight:700;color:#071952;'>👤 {current_user_name}<br><span style='color:#088395;'>{current_role} Portal</span></div>", unsafe_allow_html=True)
    if st.button("🔒 Logout", use_container_width=True):
        st.session_state.auth_session = {"logged_in": False, "user": None, "role": None}
        st.rerun()

# =========================================================================
# ABSOLUTE ISOLATION BASED ON LOGIN ROLE
# =========================================================================

if current_role == "Technician":
    tab_tech, tab_manage = st.tabs(["📝 Technician Intake Portal", "🗂️ Manage My Records"])
    
    with tab_tech:
        st.markdown("### 📝 Technician: Demographic Entry, File Upload & Clinical Parameters")
        
        c1, c2, c3 = st.columns(3)
        doc_kind = c1.selectbox("Document Format", ["NCS Report", "EEG Report", "Front Cover Page"])
        p_id = c2.text_input("Patient ID / Ref", value="1843")
        p_name = c3.text_input("Patient Name", value="Masarat John")
        
        c4, c5, c6 = st.columns(3)
        p_age = c4.text_input("Age / Gender", "42 Years / Female")
        p_date = c5.date_input("Study Date", datetime.date.today())
        p_addr = c6.text_input("Address", "Kulgam")
        
        c7, c8, c9 = st.columns(3)
        p_ref = c7.text_input("Referring Physician", "Dr Aejaz Ahmad")
        p_neuro = c8.selectbox("Consultant Neurologist", ["Dr Rayees Ahmad Tarray (DM Neurology)", "Dr. Aadil Majeed (DrNB Neurology)"])
        p_fee = c9.number_input("Diagnostic Fee (INR)", value=1500.0, step=100.0)

        st.markdown("---")
        st.subheader("2. Upload Machine Scans, Graphs & Documents")
        gu, su = st.columns(2)
        graph_file = gu.file_uploader("📊 Upload Machine Graph / Trace / PDF", type=['png', 'jpg', 'jpeg', 'pdf'])
        summary_file = su.file_uploader("📝 Upload Tech Summary Document / PDF", type=['png', 'jpg', 'jpeg', 'pdf'])

        st.markdown("---")
        st.subheader("3. Electrophysiological Parameters & Observations")
        if doc_kind == "NCS Report":
            sampled_nerves = st.text_area("Sampled Nerves & Protocol", value="Motor: Bilateral Peroneal, Tibial, Median & Ulnar Nerves.\nSensory: Bilateral Sural Median & Ulnar Nerves.")
            motor_findings = st.text_area("Motor Findings (Latencies, Amplitudes, CV)", value="Bilateral Ulnar and Tibial Nerves: Normal DML, CMAP and CV.\nBilateral Peroneal: Normal DML and CV.")
            sensory_findings = st.text_area("Sensory Findings", value="Normal Latency, Amplitude and CV.")
            f_waves = st.text_area("F-Wave Latencies", value="Normal minimum latencies.")
            bg_activity, epi_activity, activation = "", "", ""
        elif doc_kind == "EEG Report":
            sampled_nerves, motor_findings, sensory_findings, f_waves = "", "", "", ""
            bg_activity = st.text_area("Background Activity", value="Symmetric, well-regulated 9-10 Hz posterior alpha rhythm.")
            epi_activity = st.text_area("Epileptiform Discharges", value="- No focal slowing or spike-wave discharges observed.")
            activation = st.text_area("Activation & Artifacts", value="- Normal physiological responses to photic stimulation.")
        else:
            sampled_nerves, motor_findings, sensory_findings, f_waves = "", "", "", ""
            bg_activity, epi_activity, activation = "", "", ""

        t_summary_text = st.text_area("Additional Technician Remarks", placeholder="Enter any specific technical notes for the neurologist...")

        if st.button("📤 Submit Complete Case to Doctor's Queue", use_container_width=True):
            g_b64, g_type, s_b64, s_type = "", "", "", ""
            if graph_file:
                g_b64 = f"data:{graph_file.type};base64,{base64.b64encode(graph_file.read()).decode('utf-8')}"
                g_type = graph_file.type
            if summary_file:
                s_b64 = f"data:{summary_file.type};base64,{base64.b64encode(summary_file.read()).decode('utf-8')}"
                s_type = summary_file.type

            conn = get_db_connection()
            cur = conn.cursor()
            status = "Finalized" if doc_kind == "Front Cover Page" else "Pending Doctor Review"
            now_ts = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
            
            cur.execute("""
                INSERT INTO patients (
                    patient_id, patient_name, study_date, age_gender, address,
                    ref_physician, rep_physician, technician, doc_kind,
                    sampled_nerves, motor_findings, sensory_findings, f_waves,
                    bg_activity, epi_activity, activation,
                    tech_summary, graph_data, graph_type, summary_data, summary_type,
                    billing_amount, payment_status, status, generation_date, despatch_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Unpaid', ?, ?, ?)
            """, (
                p_id, p_name, p_date.strftime("%d-%m-%Y"), p_age, p_addr,
                p_ref, p_neuro, current_user_name, doc_kind,
                sampled_nerves, motor_findings, sensory_findings, f_waves,
                bg_activity, epi_activity, activation,
                t_summary_text, g_b64, g_type, s_b64, s_type, p_fee, status, now_ts, now_ts
            ))
            conn.commit()
            conn.close()
            st.success("✅ Case successfully submitted with all data and files!")

    with tab_manage:
        st.markdown("### 🗂️ Manage Uploaded Records (Hold, Release, Print)")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE is_archived = 0 ORDER BY id DESC LIMIT 50")
        manage_cases = cur.fetchall()
        conn.close()

        for r in manage_cases:
            with st.container(border=True):
                col1, col2 = st.columns([3, 2])
                with col1:
                    st.markdown(f"**{r['patient_name']}** (ID: `{r['patient_id']}`) • Modality: `{r['doc_kind']}`")
                    st.caption(f"Status: **{r['status']}** | Gen Date: {r['generation_date'] if r['generation_date'] else 'N/A'}")
                with col2:
                    action_c1, action_c2 = st.columns(2)
                    
                    if r['status'] == 'Pending Doctor Review':
                        if action_c1.button("⏸️ Hold Record", key=f"thold_{r['id']}", use_container_width=True):
                            update_patient_status(r['id'], 'On Hold')
                    elif r['status'] == 'On Hold':
                        if action_c1.button("▶️ Release", key=f"trel_{r['id']}", use_container_width=True):
                            update_patient_status(r['id'], 'Pending Doctor Review')
                    else:
                        action_c1.button("✅ Completed", disabled=True, key=f"tdone_{r['id']}", use_container_width=True)

                    html_rep = build_report_html(r)
                    with st.expander("👁️ Preview Report"):
                        components.html(html_rep, height=400, scrolling=True)

                    if PDF_ENGINE_AVAILABLE:
                        last_name = r['patient_name'].strip().split()[-1]
                        pdf_password = (last_name + r['patient_id']).lower().replace(" ", "")
                        pdf_data, err = generate_pdf(html_rep, pdf_password)
                        if pdf_data:
                            action_c2.download_button("🖨️ Download PDF", data=pdf_data, file_name=f"{r['patient_name']}_Report.pdf", mime="application/pdf", key=f"tpdf_{r['id']}", use_container_width=True)
                        else:
                            action_c2.error(f"PDF Gen Error: {err}")
                    else:
                        action_c2.error("⚠️ PDF Engine Unavailable.")
                        action_c2.download_button("🖨️ Print HTML", data=html_rep, file_name=f"{r['patient_name']}_Report.html", mime="text/html", key=f"thtml_{r['id']}", use_container_width=True)

elif current_role == "Doctor":
    tab_doc, tab_modify, tab_archive = st.tabs(["🩺 Doctor Review Portal", "🗂️ Modify / Rewrite Finalized Reports", "📦 Archived Vault"])
    
    with tab_doc:
        st.markdown("### 🩺 Doctor: Structured Review & Sign-Off Portal")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE status = 'Pending Doctor Review' ORDER BY id ASC")
        pending_cases = cur.fetchall()
        conn.close()

        if not pending_cases:
            st.info("✅ No cases currently pending your review.")
        else:
            for case in pending_cases:
                with st.expander(f"🔍 Review Case: {case['patient_name']} (ID: {case['patient_id']}) - {case['doc_kind']}", expanded=True):
                    c_left, c_right = st.columns([1, 1.1])
                    
                    with c_left:
                        st.markdown("#### 📂 Tech Uploaded Data & Files")
                        if case['graph_data']:
                            g_b64_data = case['graph_data'].split(',')[1]
                            g_bytes = base64.b64decode(g_b64_data)
                            st.download_button("📥 Download Graph", data=g_bytes, file_name=f"{case['patient_name']}_Graph.pdf" if 'pdf' in case['graph_type'].lower() else f"{case['patient_name']}_Graph.png", mime=case['graph_type'], key=f"d_g_{case['id']}")
                            
                            if 'pdf' in case['graph_type'].lower():
                                st.markdown(f'<iframe src="data:application/pdf;base64,{g_b64_data}" width="100%" height="250px" style="border:1px solid #ccc; border-radius:4px;"></iframe>', unsafe_allow_html=True)
                            else:
                                st.image(g_bytes, use_container_width=True)
                        
                        st.markdown("**Technician Findings & Remarks:**")
                        st.info(case['tech_summary'] or "No notes provided.")

                    with c_right:
                        st.markdown("#### ✍️ Structured Specialist Sign-Off Form")
                        
                        with st.form(f"sign_form_{case['id']}"):
                            st.markdown("##### 1. SAMPLED NERVES & PROTOCOL")
                            d_nerves = st.text_area("Protocol", value=case['sampled_nerves'] or "Motor: Bilateral Peroneal, Tibial, Median & Ulnar Nerves.\nSensory: Bilateral Sural Median & Ulnar Nerves.", height=68, key=f"dn_{case['id']}")
                            
                            st.markdown("##### 2. FINDINGS")
                            d_motor = st.text_area("MOTOR:", value=case['motor_findings'] or "Normal DML, CMAP and CV.", height=80, key=f"dm_{case['id']}")
                            d_sensory = st.text_area("SENSORY:", value=case['sensory_findings'] or "Normal Latency, Amplitude and CV.", height=80, key=f"ds_{case['id']}")
                            d_fwaves = st.text_area("F-WAVES:", value=case['f_waves'] or "Normal minimum latencies.", height=68, key=f"df_{case['id']}")
                            
                            st.markdown("##### 3. DIAGNOSTIC IMPRESSION")
                            d_impression = st.text_area("Impression", value=case['impression'] or "Descriptive EPS of sampled nerves is within normal physiological limits.", height=90, key=f"di_{case['id']}")
                            
                            if st.form_submit_button("✍️ Finalize, Sign & Publish Official Report", use_container_width=True):
                                sign_ts = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
                                conn = get_db_connection()
                                cur = conn.cursor()
                                cur.execute("""
                                    UPDATE patients 
                                    SET sampled_nerves=?, motor_findings=?, sensory_findings=?, f_waves=?, impression=?, status='Finalized', despatch_date=? 
                                    WHERE id=?
                                """, (d_nerves, d_motor, d_sensory, d_fwaves, d_impression, sign_ts, case['id']))
                                conn.commit()
                                conn.close()
                                st.success("✅ Report signed and successfully published to Patient Archive!")
                                st.rerun()

    with tab_modify:
        st.markdown("### 🗂️ Pull & Rewrite Finalized Reports")
        st.caption("Search through previously signed reports, preview attached tech scans, modify findings, and re-sign.")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE status = 'Finalized' AND is_archived = 0 ORDER BY id DESC")
        finalized_cases = cur.fetchall()
        conn.close()

        search_mod = st.text_input("🔍 Search Finalized Records by Patient Name or ID...", key="search_mod_input")

        for r in finalized_cases:
            if search_mod.lower() in r['patient_name'].lower() or search_mod.lower() in r['patient_id'].lower():
                with st.container(border=True):
                    st.markdown(f"**{r['patient_name']}** (ID: `{r['patient_id']}`) • Modality: `{r['doc_kind']}` | Study Date: {r['study_date']}")
                    
                    html_rep = build_report_html(r)
                    with st.expander("👁️ Preview Official Report"):
                        components.html(html_rep, height=500, scrolling=True)

                    if r['graph_data']:
                        with st.expander("📂 Preview Technician Uploaded Graph / PDF Trace"):
                            g_b64_data_m = r['graph_data'].split(',')[1]
                            if 'pdf' in r['graph_type'].lower():
                                st.markdown(f'<iframe src="data:application/pdf;base64,{g_b64_data_m}" width="100%" height="300px" style="border:1px solid #ccc; border-radius:4px;"></iframe>', unsafe_allow_html=True)
                            else:
                                g_bytes_m = base64.b64decode(g_b64_data_m)
                                st.image(g_bytes_m, use_container_width=True)

                    with st.form(f"rewrite_form_{r['id']}"):
                        st.markdown("##### 1. SAMPLED NERVES & PROTOCOL")
                        rw_nerves = st.text_area("Protocol", value=r['sampled_nerves'] or "None", height=60, key=f"rwn_{r['id']}")
                        
                        st.markdown("##### 2. FINDINGS")
                        rw_motor = st.text_area("MOTOR:", value=r['motor_findings'] or "None", height=70, key=f"rwm_{r['id']}")
                        rw_sensory = st.text_area("SENSORY:", value=r['sensory_findings'] or "None", height=70, key=f"rws_{r['id']}")
                        rw_fwaves = st.text_area("F-WAVES:", value=r['f_waves'] or "None", height=60, key=f"rwf_{r['id']}")
                        
                        st.markdown("##### 3. DIAGNOSTIC IMPRESSION")
                        rw_impression = st.text_area("Impression", value=r['impression'] or "", height=80, key=f"rwi_{r['id']}")
                        
                        col_b1, col_b2 = st.columns(2)
                        if col_b1.form_submit_button("💾 Save Re-written Changes", use_container_width=True):
                            update_ts = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE patients 
                                SET sampled_nerves=?, motor_findings=?, sensory_findings=?, f_waves=?, impression=?, despatch_date=? 
                                WHERE id=?
                            """, (rw_nerves, rw_motor, rw_sensory, rw_fwaves, rw_impression, update_ts, r['id']))
                            conn.commit()
                            conn.close()
                            st.success("✅ Report successfully updated!")
                            st.rerun()

                        if col_b2.form_submit_button("⏸️ Put Back on Hold (Review Queue)", use_container_width=True):
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("UPDATE patients SET status='On Hold' WHERE id=?", (r['id'],))
                            conn.commit()
                            conn.close()
                            st.warning("⚠️ Report sent back to hold queue.")
                            st.rerun()

    with tab_archive:
        st.markdown("### 📦 Archived Vault (Doctor View)")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE is_archived = 1 ORDER BY id DESC LIMIT 25")
        archived_cases = cur.fetchall()
        conn.close()
        for r in archived_cases:
            st.write(f"• **{r['patient_name']}** ({r['doc_kind']}) — Impression: {r['impression']}")
            with st.expander("👁️ Preview"):
                components.html(build_report_html(r), height=400, scrolling=True)

elif current_role == "Admin":
    tab_tech, tab_doc, tab_archive, tab_finance, tab_master, tab_admin = st.tabs([
        "📝 Tech Entry", "🩺 Doctor Review", "🗂️ Patient Archive", "💰 Invoicing & Finance", "📑 Master Report", "⚙️ Admin & Branding"
    ])
    
    with tab_tech:
        st.markdown("### 📝 Admin Tech Override Entry")
        with st.form("admin_tech_form"):
            p_id = st.text_input("Patient ID", value="1843")
            p_name = st.text_input("Patient Name", value="Masarat John")
            doc_kind = st.selectbox("Modality", ["NCS Report", "EEG Report", "Front Cover Page"])
            if st.form_submit_button("Submit Case"):
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("INSERT INTO patients (patient_id, patient_name, study_date, doc_kind, status, technician) VALUES (?, ?, ?, ?, 'Pending Doctor Review', 'Admin')", (p_id, p_name, datetime.date.today().strftime("%d-%m-%Y"), doc_kind))
                conn.commit()
                conn.close()
                st.success("Case added.")

    with tab_doc:
        st.markdown("### 🩺 Admin Doctor Review Queue")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients WHERE status = 'Pending Doctor Review'")
        pendings = cur.fetchall()
        conn.close()
        for p in pendings:
            st.write(f"• Pending Review: **{p['patient_name']}** ({p['patient_id']})")

    with tab_archive:
        st.markdown("### 🗂️ Complete Patient Archive (Admin)")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients ORDER BY id DESC")
        all_cases = cur.fetchall()
        conn.close()
        for r in all_cases:
            st.write(f"• **{r['patient_name']}** | ID: `{r['patient_id']}` | Status: `{r['status']}`")
            with st.expander("👁️ Preview HTML Report"):
                components.html(build_report_html(r), height=400, scrolling=True)

    with tab_finance:
        st.markdown("### 💰 Financials & Revenue Tracking")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT SUM(billing_amount) as rev FROM patients")
        tot = cur.fetchone()['rev'] or 0.0
        st.metric("Total Clinic Revenue", f"₹ {tot:,.2f}")
        conn.close()

    with tab_master:
        st.markdown("### 📑 Master Consolidated Patient Report")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM patients ORDER BY id DESC")
        all_patients = cur.fetchall()
        conn.close()
        if st.button("🖨️ Generate Master PDF Register", use_container_width=True):
            if PDF_ENGINE_AVAILABLE:
                rows_html = "".join([f"<tr><td style='padding:6px; border-bottom:1px solid #ccc;'>{p['patient_id']}</td><td style='padding:6px; border-bottom:1px solid #ccc;'>{p['patient_name']}</td><td style='padding:6px; border-bottom:1px solid #ccc;'>{p['doc_kind']}</td><td style='padding:6px; border-bottom:1px solid #ccc;'>{p['status']}</td></tr>" for p in all_patients])
                master_html = f"<html><head><style>body{{font-family:sans-serif;}} table{{width:100%; border-collapse:collapse;}} th{{background:#071952; color:white; padding:8px; text-align:left;}}</style></head><body><h2>Clinic Master Register</h2><table><tr><th>ID</th><th>Name</th><th>Modality</th><th>Status</th></tr>{rows_html}</table></body></html>"
                pdf_bytes, _ = generate_pdf(master_html)
                if pdf_bytes:
                    b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                    st.markdown(f'<a href="data:application/pdf;base64,{b64}" download="Master_Report.pdf" style="display:inline-block; padding:8px 16px; background:#088395; color:white; text-decoration:none; border-radius:6px; font-weight:bold;">📥 Download Master PDF File</a>', unsafe_allow_html=True)
                else:
                    st.error("Failed to generate PDF.")
            else:
                st.error("⚠️ PDF Engine is not available. Please install system libraries (GTK3).")

    with tab_admin:
        st.markdown("### ⚙️ Admin Control Center: Branding, AI & User Permissions")
        adm_sub1, adm_sub2 = st.tabs(["🏛️ Clinic Header, Branding & AI", "👥 User Access & PIN Management"])
        
        with adm_sub1:
            curr_sets = get_settings()
            with st.form("branding_form"):
                new_c_name = st.text_input("Clinic / Hospital Name", value=curr_sets.get('clinic_name', ''))
                new_c_sub = st.text_input("Department / Sub-Header", value=curr_sets.get('sub_header', ''))
                new_ai_key = st.text_input("Global AI API Key (For Clinical AI Assist)", type="password", value=curr_sets.get('ai_api_key', ''))
                new_logo_file = st.file_uploader("Upload Institutional Logo (PNG/JPG)", type=['png', 'jpg', 'jpeg'])
                
                if st.form_submit_button("💾 Save Institutional Configuration"):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE portal_settings SET setting_value=? WHERE setting_key='clinic_name'", (new_c_name,))
                    cur.execute("UPDATE portal_settings SET setting_value=? WHERE setting_key='sub_header'", (new_c_sub,))
                    cur.execute("UPDATE portal_settings SET setting_value=? WHERE setting_key='ai_api_key'", (new_ai_key.strip(),))
                    
                    if new_logo_file:
                        l_b64 = base64.b64encode(new_logo_file.read()).decode('utf-8')
                        full_l = f"data:{new_logo_file.type};base64,{l_b64}"
                        cur.execute("UPDATE portal_settings SET setting_value=? WHERE setting_key='logo_b64'", (full_l,))
                    
                    conn.commit()
                    conn.close()
                    st.success("✅ Configuration updated successfully!")
                    st.rerun()
            
            if curr_sets.get('logo_b64'):
                st.image(curr_sets['logo_b64'], width=180, caption="Current Active Logo")
                if st.button("🗑️ Remove Logo"):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE portal_settings SET setting_value='' WHERE setting_key='logo_b64'")
                    conn.commit()
                    conn.close()
                    st.rerun()

        with adm_sub2:
            st.markdown("#### 👥 Active Staff Permissions & Modification")
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM portal_users")
            users = cur.fetchall()
            
            for u in users:
                with st.expander(f"👤 {u['full_name']} ({u['role']}) — PIN: `{u['access_pin']}`"):
                    with st.form(f"edit_user_{u['id']}"):
                        e_name = st.text_input("Full Name", value=u['full_name'], key=f"ename_{u['id']}")
                        e_contact = st.text_input("Contact Email / Phone", value=u['email_or_phone'], key=f"econt_{u['id']}")
                        
                        roles_list = ["Admin", "Doctor", "Technician"]
                        r_idx = roles_list.index(u['role']) if u['role'] in roles_list else 2
                        e_role = st.selectbox("Role", roles_list, index=r_idx, key=f"erole_{u['id']}")
                        
                        e_pin = st.text_input("Access PIN", value=u['access_pin'], key=f"epin_{u['id']}")
                        
                        col_e1, col_e2 = st.columns(2)
                        if col_e1.form_submit_button("💾 Update User Details"):
                            cur.execute("SELECT id FROM portal_users WHERE access_pin = ? AND id != ?", (e_pin.strip(), u['id']))
                            conflict = cur.fetchone()
                            if conflict:
                                st.error("⚠️ This Access PIN is already assigned to another user.")
                            else:
                                try:
                                    cur.execute("UPDATE portal_users SET full_name=?, email_or_phone=?, role=?, access_pin=? WHERE id=?", (e_name, e_contact, e_role, e_pin.strip(), u['id']))
                                    conn.commit()
                                    st.success("✅ User updated successfully!")
                                    st.rerun()
                                except Exception as ex:
                                    st.error(f"Error updating user: {ex}")
                                
                        if col_e2.form_submit_button("🗑️ Revoke User Access"):
                            cur.execute("DELETE FROM portal_users WHERE id=?", (u['id'],))
                            conn.commit()
                            st.warning("⚠️ User access revoked.")
                            st.rerun()
            
            st.markdown("---")
            st.markdown("#### ➕ Add New User PIN")
            with st.form("new_user_form"):
                nu_name = st.text_input("Full Name")
                nu_contact = st.text_input("Contact Email / Phone")
                nu_role = st.selectbox("Role", ["Doctor", "Technician", "Admin"])
                nu_pin = st.text_input("Access PIN", value="".join(random.choices(string.digits, k=4)))
                if st.form_submit_button("Grant User Access"):
                    if nu_name and nu_pin:
                        try:
                            cur.execute("INSERT INTO portal_users (full_name, email_or_phone, role, access_pin, status) VALUES (?, ?, ?, ?, 'APPROVED')", (nu_name, nu_contact, nu_role, nu_pin))
                            conn.commit()
                            st.success(f"User {nu_name} created successfully!")
                            st.rerun()
                        except:
                            st.error("PIN already exists.")
            conn.close()