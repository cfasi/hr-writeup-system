# app.py
import os
import re
import math
import requests
import streamlit as st
import pandas as pd
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import date, datetime

# -----------------------------
# Load environment variables
# -----------------------------
load_dotenv(".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Optional Slack webhooks (leave blank if not using)
SLACK_ALERT_WEBHOOK_URL = os.getenv("SLACK_ALERT_WEBHOOK_URL", "").strip()      # alerts: borderline/suspension/fired
SLACK_WRITEUP_WEBHOOK_URL = os.getenv("SLACK_WRITEUP_WEBHOOK_URL", "").strip()  # writeup log channel

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Missing SUPABASE_URL or SUPABASE_KEY in your .env file.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------
# Streamlit config
# -----------------------------
st.set_page_config(page_title="HR Write-Up System", layout="centered")
st.title("HR Write-Up System")

# -----------------------------
# Quarter Standing Benchmarks (per quarter; resets each quarter)
# -----------------------------
BENCHMARKS = {
    "Good Standing": {"min": 0, "max": 9, "color": "#28a745"},   # green
    "Borderline": {"min": 10, "max": 19, "color": "#ffc107"},    # yellow
    "Suspension": {"min": 20, "max": 24, "color": "#fd7e14"},    # orange
    "Fired": {"min": 25, "max": 10**9, "color": "#dc3545"},      # red
}
STANDING_ORDER = ["Good Standing", "Borderline", "Suspension", "Fired"]

# -----------------------------
# Handbook codes shown in Manager Mode when a Reason/Rule is selected
# Key MUST match your rule_name exactly (case + spacing)
# -----------------------------
HANDBOOK_BY_RULE = {
    "No Call No Show": (
        "Employees are expected to be punctual and regular in attendance. Employees are expected to report to work "
        "as scheduled, on time and prepared to start work at the beginning of their shifts and at the end of meal "
        "periods. Late arrival, early departure or other absences from scheduled hours are disruptive and should be avoided."
    ),

    "Late by 6 or more minutes": (
        "Employees are expected to be punctual and regular in attendance. Employees are expected to report to work "
        "as scheduled, on time and prepared to start work at the beginning of their shifts and at the end of meal "
        "periods. Late arrival, early departure or other absences from scheduled hours are disruptive and should be avoided."
    ),


    "Called out with less than 2 hour notice": (
        "If you will be absent from or tardy for work for any reason, you must call your supervisor as soon as possible, "
        "but at least two hours before the beginning of your scheduled shift, and advise of the reason for your absence "
        "or tardiness and when you expect to return to work. Obviously, if you know of a required absence from work in advance, "
        "you must inform your supervisor as far in advance as possible, so that Chick-fil-A at Staten Island Mall can adjust "
        "the work schedule accordingly. In certain instances, subject to applicable law, if an absence is to exceed one day, "
        "you may be required to provide your supervisor with an update at the beginning of each day of the absence, until a "
        "return to work date has been established.\n\n"
        "Chick-fil-A at Staten Island Mall reserves the right to discipline employees for unexcused absences (including late arrivals "
        "or early departures), up to and including termination of employment, in accordance with the Progressive Discipline Policy."
    ),

    "Called out without finding coverage": (
        "If you will be absent from or tardy for work for any reason, you must call your supervisor as soon as possible, "
        "but at least two hours before the beginning of your scheduled shift, and advise of the reason for your absence "
        "or tardiness and when you expect to return to work. Obviously, if you know of a required absence from work in advance, "
        "you must inform your supervisor as far in advance as possible, so that Chick-fil-A at Staten Island Mall can adjust "
        "the work schedule accordingly. In certain instances, subject to applicable law, if an absence is to exceed one day, "
        "you may be required to provide your supervisor with an update at the beginning of each day of the absence, until a "
        "return to work date has been established.\n\n"
        "Chick-fil-A at Staten Island Mall reserves the right to discipline employees for unexcused absences (including late arrivals "
        "or early departures), up to and including termination of employment, in accordance with the Progressive Discipline Policy."
    ),

    "Called out 4 times in one month": (
        "Chick-fil-A at Staten Island Mall reserves the right to discipline employees for unexcused absences (including late arrivals "
        "or early departures), up to and including termination of employment, in accordance with the Progressive Discipline Policy. "
        "Excessive absenteeism or tardiness."
    ),

    "Exceeded break time by 3 or more minutes": (
        "Employees also are expected to remain at work for their entire work schedule, except for meal periods or when required to leave "
        "on authorized Chick-fil-A at Staten Island Mall business."
    ),

    "Staying past scheduled time (5+ minutes)": (
        "Non-exempt employees are not permitted to work beyond their normal work schedule without the express written approval of their "
        "Director or the Owner/Operator."
    ),

    "Incomplete uniform": (
        "All uniforms items (including belts, outerwear, and caps) must be from Chick-fil-A team style collection. All garments should fit properly "
        "and be cleaned, pressed, (as applicable) and in good condition (i.e., no holes, fraying, stains, discoloring, etc.)."
    ),

    "Drawer short/over $10+": (
        "You are responsible for the cash and coupons that you process during your shift. It is necessary in our business that we take this "
        "Cash and Coupon Accountability Policy extremely seriously. Any action by an employee contrary to this policy will result in disciplinary action, "
        "up to and including termination of employment, in accordance with the Progressive Discipline Policy."
    ),

    "Drawer short/over $3+": (
        "You are responsible for the cash and coupons that you process during your shift. It is necessary in our business that we take this "
        "Cash and Coupon Accountability Policy extremely seriously. Any action by an employee contrary to this policy will result in disciplinary action, "
        "up to and including termination of employment, in accordance with the Progressive Discipline Policy."
    ),


    "Damaging equipment due to negligence": """
**Egregious Misconduct**

Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

- Abuse, damage or deliberate destruction of Chick-fil-A at Staten Island Mall’s or a guest’s property or the property of Chick-fil-A at Staten Island Mall employees or vendors.

""",

    "Poor work performance": """
**Egregious Misconduct**

Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

- Failure to maintain satisfactory productivity and quality of work.
""",

    "Breach of safety procedures": """
**Egregious Misconduct**

Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

- Failing to properly report an injury or accident or falsely claiming injury.
- Violation of or disregard of the rules and regulations stated in this manual or in other Chick-fil-A at Staten Island Mall policy.
""",

    "Using cell phone for personal use": (
        "Unless otherwise authorized by a director or the Owner/Operator, cell phones and other personal electronic devices may not be visible or used while you are working. "
        "If you choose to bring a personal cell phone or similar device to work, it must be turned off or to “silent” mode so as not to be disruptive to the workplace.\n\n"
        "Chick-fil-A at Staten Island Mall prohibits employees from using any personal electronic device while driving during work time or while operating "
        "Chick-fil-A at Staten Island Mall vehicles, equipment or machinery. Violation of this policy may lead to disciplinary action, up to and including termination "
        "of employment, in accordance with the Progressive Discipline Policy."
    ),


    "Engaging in personal work while on the clock": """
**Egregious Misconduct**

Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

- Outside employment or activities which interfere with regular working hours or productivity.
""",

    "Failure to fulfill job expectations": """
**Egregious Misconduct**

Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

- Failure to maintain satisfactory productivity and quality of work.
""",

    "Harassment, bullying, or victimization": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Making false or disparaging statements or spreading rumors.
        - Use of profanity or abusive language toward employees, guests, or vendors.
        - Violence or threatening behavior.
        - Disorderly conduct on company property.
        """,

    "Disrespectful behavior": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Making false and disparaging statements or spreading rumors which might harm the reputation of our employees or guests.
        - Use of profanity or abusive language toward employees, guests or other persons on Chick-fil-A at Staten Island Mall’s premises or while performing Chick-fil-A at Staten Island Mall work.
        - Violence or threatening behavior.
        - Disorderly conduct on Chick-fil-A at Staten Island Mall property, such as horseplay, threatening, insulting or abusing any employee, guest or vendor or fighting or attempting bodily injury of anyone..
        """,


    "Refusal to obey management instructions": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Insubordination or refusal or failure to obey instructions.

        """,

    "Use of profanity": (
        "Use of profanity or abusive language toward employees, guests or other persons on Chick-fil-A at Staten Island Mall’s premises "
        "or while performing Chick-fil-A at Staten Island Mall work."
    ),



    "Violent behavior": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Violence or threatening behavior.
        - Disorderly conduct on Chick-fil-A at Staten Island Mall property, such as horseplay, threatening, insulting or abusing any employee, guest or vendor or fighting or attempting bodily injury of anyone.
        """,

    "Theft or fraud": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Theft, misuse or unauthorized possession or removal of Chick-fil-A at Staten Island Mall, employee, vendor or guest property. 

        """,


    "Endangering health or safety": """
        **Egregious Misconduct**

        Includes criminal conduct or conduct that seriously harms or immediately threatens the health and safety of other employees or members of the public, including, without limitation:

        - Disorderly conduct on Chick-fil-A at Staten Island Mall property, such as horseplay, threatening, insulting or abusing any employee, guest or vendor, or fighting or attempting bodily injury of anyone.
        - Using, possessing, passing, or selling, or working or reporting to work under the influence of, alcoholic beverages or any drug, narcotic or other controlled substance on Chick-fil-A at Staten Island Mall premises at any time or while performing Chick-fil-A at Staten Island Mall work.
        - Possession of dangerous weapons or firearms on Chick-fil-A at Staten Island Mall premises.
        """,

    "Leaving workplace without permission": (
        "Employees are expected to be punctual and regular in attendance. Employees are expected to report to work as scheduled, on time and prepared to start work at the beginning "
        "of their shifts and at the end of meal periods. Late arrival, early departure or other absences from scheduled hours are disruptive and should be avoided."
    ),
}


def standing_label(points: int) -> str:
    p = int(points or 0)
    if p < 10:
        return "Good Standing"
    if 10 <= p <= 19:
        return "Borderline"
    if 20 <= p <= 24:
        return "Suspension"
    return "Fired"


def standing_color(label: str) -> str:
    return BENCHMARKS.get(label, {}).get("color", "#6c757d")


def standing_badge(label: str, points: int, caption: str = ""):
    color = standing_color(label)
    st.markdown(
        f"""
        <div style="
            padding: 12px 14px;
            border-radius: 10px;
            background: {color};
            color: white;
            font-weight: 800;
            display: inline-block;
            margin-bottom: 6px;
        ">
            {label} — {int(points or 0)} pts
        </div>
        """,
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(caption)


# -----------------------------
# Initialize session state
# -----------------------------
defaults = {
    "logged_in": False,
    "username": "",
    "role": "",
    "pending_delete_writeup_id": None,
    "pending_delete_member_id": None,
    "pending_delete_category_id": None,
    "pending_delete_username": None,
    "search_name": "",
    "selected_member_id": None,

    # Admin chronological browser
    "admin_browse_index": 0,
    "admin_browse_ids": [],
    "admin_browse_cache": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------------
# Date + Quarter helpers
# -----------------------------
def parse_iso_date(d):
    if not d:
        return None
    try:
        if isinstance(d, str):
            return datetime.fromisoformat(d.replace("Z", "+00:00")).date()
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, date):
            return d
    except Exception:
        return None
    return None


def quarter_key(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year} Q{q}"


def current_quarter_key(today: date = None) -> str:
    today = today or date.today()
    return quarter_key(today)


def build_quarter_totals(writeups: list) -> pd.DataFrame:
    bucket = {}
    for w in (writeups or []):
        d = parse_iso_date(w.get("incident_date"))
        if not d:
            continue
        k = quarter_key(d)
        bucket[k] = bucket.get(k, 0) + int(w.get("points") or 0)

    df = pd.DataFrame([{"quarter": k, "points": v} for k, v in bucket.items()])
    if df.empty:
        return df

    def _sort_key(qstr):
        y, q = qstr.split()
        return int(y), int(q.replace("Q", ""))

    df["sort"] = df["quarter"].apply(_sort_key)
    df = df.sort_values("sort").drop(columns=["sort"]).reset_index(drop=True)
    return df


def points_in_quarter(writeups: list, quarter_label: str) -> int:
    total = 0
    for w in (writeups or []):
        d = parse_iso_date(w.get("incident_date"))
        if not d:
            continue
        if quarter_key(d) == quarter_label:
            total += int(w.get("points") or 0)
    return total


def all_time_points(writeups: list) -> int:
    return sum(int(w.get("points") or 0) for w in (writeups or []))


# -----------------------------
# Late points logic (your custom scale)
# -----------------------------
def calc_late_points(minutes_late: int) -> int:
    if minutes_late is None:
        return 0
    m = int(minutes_late)
    if m < 6:
        return 0
    return 1 + (m - 5) // 10


# -----------------------------
# Notes formatting for full write-up packet
# -----------------------------
def format_writeup_notes(
    reason: str,
    manager_notes: str,
    secondary_lead_witness: str,
    corrective_actions: str,
    team_member_comments: str,
    team_member_signature: str,
    leader_signature: str,
    secondary_leader_signature: str,
    signed_date: date,
) -> str:
    reason = (reason or "").strip()
    manager_notes = (manager_notes or "").strip()
    secondary_lead_witness = (secondary_lead_witness or "").strip()
    corrective_actions = (corrective_actions or "").strip()
    team_member_comments = (team_member_comments or "").strip()
    team_member_signature = (team_member_signature or "").strip()
    leader_signature = (leader_signature or "").strip()
    secondary_leader_signature = (secondary_leader_signature or "").strip()

    parts = []
    parts.append(f"Reason: {reason}")

    if manager_notes:
        parts.append("\nManager Notes:\n" + manager_notes)
    if secondary_lead_witness:
        parts.append("\nSecondary Lead Witnessing Write-Up:\n" + secondary_lead_witness)
    if corrective_actions:
        parts.append("\nCorrective Actions:\n" + corrective_actions)
    if team_member_comments:
        parts.append("\nTeam Member Comments:\n" + team_member_comments)

    parts.append("\nSignatures:")
    parts.append(f"- Team Member Signature: {team_member_signature if team_member_signature else '________________'}")
    parts.append(f"- Leader Signature: {leader_signature if leader_signature else '________________'}")
    parts.append(
        f"- Secondary Leader Signature: {secondary_leader_signature if secondary_leader_signature else '________________'}"
    )
    parts.append(f"- Date Signed: {signed_date.isoformat() if signed_date else date.today().isoformat()}")

    return "\n".join(parts)


# -----------------------------
# Slack helpers
# -----------------------------
def slack_post(webhook_url: str, text: str):
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"text": text}, timeout=10)
    except Exception:
        pass


def extract_lead_names_from_notes(notes: str):
    if not notes:
        return "", ""
    leader = ""
    secondary = ""
    m1 = re.search(r"Leader Signature:\s*(.*)", notes)
    m2 = re.search(r"Secondary Leader Signature:\s*(.*)", notes)
    if m1:
        leader = (m1.group(1) or "").strip()
    if m2:
        secondary = (m2.group(1) or "").strip()
    return leader, secondary


def extract_reason_from_notes(notes: str):
    if not notes:
        return ""
    m = re.search(r"^Reason:\s*(.*)$", notes, flags=re.MULTILINE)
    return (m.group(1).strip() if m else "")


def post_writeup_to_slack(member_name: str, category_name: str, incident_date: str, notes: str):
    if not SLACK_WRITEUP_WEBHOOK_URL:
        return
    reason = extract_reason_from_notes(notes)
    leader, secondary = extract_lead_names_from_notes(notes)
    msg = (
        f"*New Write-Up Logged*\n"
        f"• Date: {incident_date}\n"
        f"• Team Member: {member_name}\n"
        f"• Category: {category_name}\n"
        f"• Reason: {reason if reason else '(not provided)'}\n"
        f"• Lead: {leader if leader else '(not provided)'}\n"
        f"• Secondary Lead: {secondary if secondary else '(not provided)'}"
    )
    slack_post(SLACK_WRITEUP_WEBHOOK_URL, msg)


def maybe_post_standing_alert(member_name: str, quarter_label: str, prev_label: str, new_label: str, q_points: int):
    if not SLACK_ALERT_WEBHOOK_URL:
        return
    watch = {"Borderline", "Suspension", "Fired"}
    if new_label in watch and new_label != prev_label:
        msg = (
            f"*Standing Alert*\n"
            f"• Team Member: {member_name}\n"
            f"• Quarter: {quarter_label}\n"
            f"• Standing: {prev_label} → *{new_label}*\n"
            f"• Quarter Points: {q_points}"
        )
        slack_post(SLACK_ALERT_WEBHOOK_URL, msg)


# -----------------------------
# Supabase helpers
# -----------------------------
def ensure_default_admin():
    resp = supabase.table("users").select("username").execute()
    if not resp.data:
        supabase.table("users").insert(
            {"username": "Lauren", "password": "952426", "role": "admin", "is_disabled": False}
        ).execute()


def check_login(username: str, password_input: str):
    try:
        user_data = (
            supabase.from_("users")
            .select("password, role, is_disabled")
            .eq("username", username)
            .single()
            .execute()
            .data
        )
        if not user_data:
            return False, None

        # Treat missing / NULL as not disabled
        if user_data.get("is_disabled") is True:
            return False, None

        if password_input == user_data["password"]:
            return True, user_data["role"]
    except Exception:
        return False, None
    return False, None


def fetch_team_members(search: str = "", include_inactive: bool = False):
    q = supabase.from_("team_members").select("id, name, status, created_at")
    if search.strip():
        s = search.strip()
        q = q.ilike("name", f"%{s}%")
    if not include_inactive:
        q = q.neq("status", "inactive")
    q = q.order("name")
    return q.execute().data or []


def fetch_categories(include_inactive: bool = False):
    q = supabase.from_("writeup_categories").select("id, name, default_points, is_active").order("name")
    if not include_inactive:
        q = q.eq("is_active", True)
    return q.execute().data or []


def fetch_rules_for_category(category_id):
    return (
        supabase.from_("writeup_rules")
        .select("id, rule_name, base_points, is_incremental, increment_minutes, increment_points, notes")
        .eq("category_id", category_id)
        .order("rule_name")
        .execute()
        .data
        or []
    )


def fetch_writeups_for_member(member_id):
    res = (
        supabase.from_("writeups")
        .select("id, points, incident_date, notes, created_by, created_at, writeup_categories(name)")
        .eq("team_member_id", member_id)
        .order("incident_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def add_writeup(member_id, category_id, points, incident_date, notes, created_by):
    payload = {
        "team_member_id": member_id,
        "category_id": category_id,
        "points": int(points),
        "incident_date": incident_date.isoformat(),
        "notes": notes.strip() if notes else None,
        "created_by": created_by,
    }
    return supabase.from_("writeups").insert(payload).execute().data


def delete_writeup(writeup_id):
    supabase.from_("writeups").delete().eq("id", writeup_id).execute()


def add_team_member(name: str):
    return (
        supabase.from_("team_members")
        .insert({"name": name.strip(), "status": "active"})
        .execute()
        .data
    )


def set_team_member_status(member_id: str, new_status: str):
    return supabase.from_("team_members").update({"status": new_status}).eq("id", member_id).execute()


def delete_team_member(member_id: str):
    supabase.from_("writeups").delete().eq("team_member_id", member_id).execute()
    supabase.from_("team_members").delete().eq("id", member_id).execute()


def fetch_all_writeups_chronological():
    return (
        supabase.from_("writeups")
        .select(
            "id, points, incident_date, notes, created_by, created_at, "
            "team_members(name), writeup_categories(name)"
        )
        .order("incident_date", desc=True)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )


# ---- User admin helpers ----
def update_user_role(username: str, new_role: str):
    return supabase.from_("users").update({"role": new_role}).eq("username", username).execute()


def set_user_disabled(username: str, disabled: bool):
    return supabase.from_("users").update({"is_disabled": bool(disabled)}).eq("username", username).execute()


def delete_user(username: str):
    return supabase.from_("users").delete().eq("username", username).execute()


# -----------------------------
# Startup actions
# -----------------------------
ensure_default_admin()


# -----------------------------
# Login gate
# -----------------------------
def login_panel():
    st.subheader("Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role = check_login(u, p)
        if ok:
            st.session_state.logged_in = True
            st.session_state.username = u
            st.session_state.role = role
            st.success(f"Logged in as {u} ({role})")
            st.rerun()
        else:
            st.error("Invalid credentials, or user is disabled.")


def logout_button():
    with st.sidebar:
        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.role = ""
            st.session_state.pending_delete_writeup_id = None
            st.session_state.selected_member_id = None
            st.session_state.pending_delete_username = None

            st.session_state.admin_browse_cache = []
            st.session_state.admin_browse_ids = []
            st.session_state.admin_browse_index = 0

            st.rerun()


# -----------------------------
# Modes
# -----------------------------
def employee_mode():
    st.header("Employee Mode (Search + View History)")

    members = fetch_team_members("", include_inactive=False)
    if not members:
        st.info("No active team members found.")
        return

    search_mode = st.radio("Search by", ["Name", "Standing"], horizontal=True)

    per_member_writeups = {}
    all_quarters = set([current_quarter_key()])

    for m in members:
        w = fetch_writeups_for_member(m["id"])
        per_member_writeups[m["id"]] = w
        df_q = build_quarter_totals(w)
        if not df_q.empty:
            all_quarters.update(df_q["quarter"].tolist())

    def _sort_q(qstr):
        y, q = qstr.split()
        return int(y), int(q.replace("Q", ""))

    quarter_options = sorted(list(all_quarters), key=_sort_q, reverse=True)
    selected_quarter = st.selectbox("Quarter to evaluate (points reset each quarter)", quarter_options)

    if search_mode == "Name":
        name_query = st.text_input("Search by name (active only)", value="")
        filtered = members
        if name_query.strip():
            nq = name_query.strip().lower()
            filtered = [m for m in members if nq in (m["name"] or "").lower()]

        if not filtered:
            st.info("No matching active team members.")
            return

        labels = [m["name"] for m in filtered]
        name_to_id = {m["name"]: m["id"] for m in filtered}
        chosen_name = st.selectbox("Select a team member", labels)
        member_id = name_to_id[chosen_name]
    else:
        standing_choice = st.selectbox("Standing (based on selected quarter points)", STANDING_ORDER)

        rows = []
        for m in members:
            w = per_member_writeups.get(m["id"], [])
            q_total = points_in_quarter(w, selected_quarter)
            s = standing_label(q_total)
            if s == standing_choice:
                rows.append({"id": m["id"], "name": m["name"], "quarter_points": q_total})

        if not rows:
            st.info(f"No active team members found in {standing_choice} for {selected_quarter}.")
            return

        rows.sort(key=lambda r: (-int(r["quarter_points"]), r["name"].lower()))
        labels = [f"{r['name']} ({r['quarter_points']} pts)" for r in rows]
        label_to_id = {labels[i]: rows[i]["id"] for i in range(len(labels))}
        chosen = st.selectbox("Select a team member", labels)
        member_id = label_to_id[chosen]

    writeups = per_member_writeups.get(member_id) or fetch_writeups_for_member(member_id)

    q_total = points_in_quarter(writeups, selected_quarter)
    s_label = standing_label(q_total)
    a_total = all_time_points(writeups)

    standing_badge(
        s_label,
        q_total,
        caption=f"Standing is based on **{selected_quarter}** points (resets every quarter).",
    )

    c1, c2 = st.columns(2)
    c1.metric(f"Points in {selected_quarter}", q_total)
    c2.metric("All-Time Points", a_total)

    st.subheader("Points Over Time (by Quarter)")
    df_q = build_quarter_totals(writeups)
    if df_q.empty:
        st.info("No write-ups yet, so no quarter history to show.")
    else:
        st.dataframe(df_q.rename(columns={"quarter": "Quarter", "points": "Points"}),
                     hide_index=True, use_container_width=True)

    st.subheader("Write-Up History (All Time)")
    if not writeups:
        st.warning("No write-ups found.")
        return

    rows = []
    for w in writeups:
        cat = w.get("writeup_categories") or {}
        cat_name = cat.get("name") if isinstance(cat, dict) else None
        d = parse_iso_date(w.get("incident_date"))
        rows.append(
            {
                "Incident Date": w.get("incident_date"),
                "Quarter": quarter_key(d) if d else None,
                "Category": cat_name,
                "Points": w.get("points"),
                "Created By": w.get("created_by"),
                "Created At": w.get("created_at"),
                "Writeup ID": w.get("id"),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("View Full Write-Up Details (including signatures)", expanded=False):
        ids = [w["id"] for w in writeups]
        chosen_id = st.selectbox("Select Writeup ID", ids, key="emp_view_writeup_id")
        chosen_w = next((w for w in writeups if w["id"] == chosen_id), None)
        if chosen_w:
            st.text_area("Full Write-Up Details", value=chosen_w.get("notes") or "", height=260)


def manager_mode():
    st.header("Manager Mode (Add Write-Ups)")

    if st.session_state.role not in ["manager", "admin"]:
        st.error("You do not have access to Manager Mode.")
        return

    st.subheader("Find Team Member")
    member_search = st.text_input("Search team member (active only)", value="")
    members = fetch_team_members(member_search, include_inactive=False)

    if not members:
        st.info("No active team members match that search.")
        return

    member_labels = [m["name"] for m in members]
    member_map = {m["name"]: m["id"] for m in members}

    member_name = st.selectbox("Select team member", member_labels)
    member_id = member_map[member_name]

    categories = fetch_categories(include_inactive=False)
    if not categories:
        st.error("No active categories found.")
        return

    cat_names = [c["name"] for c in categories]
    cat_map = {c["name"]: c for c in categories}

    st.markdown("---")
    st.subheader("Create Write-Up")

    chosen_cat_name = st.selectbox("Category", cat_names)
    chosen_cat = cat_map[chosen_cat_name]
    category_id = chosen_cat["id"]

    # -----------------------------
    # DOCUMENTED CONVERSATION LOGIC
    # -----------------------------
    if chosen_cat_name == "Documented Conversation":

        st.info("This is a documented conversation. No points will be assigned.")

        custom_reason = st.text_input("Conversation Topic / Reason")

        auto_points = 0

    else:
        # Normal categories
        rules = fetch_rules_for_category(category_id)
        if not rules:
            st.warning("No rules found for this category.")
            return

        rule_labels = [r["rule_name"] for r in rules]
        rule_map = {r["rule_name"]: r for r in rules}

        chosen_rule_name = st.selectbox("Reason / Rule", rule_labels)

        # Show handbook if exists
        hb_text = HANDBOOK_BY_RULE.get(chosen_rule_name)
        if hb_text:
            st.markdown("#### Employee Handbook Code")
            st.info(hb_text)

        chosen_rule = rule_map[chosen_rule_name]
        auto_points = int(chosen_rule.get("base_points") or 0)

        if chosen_rule.get("is_incremental"):
            minutes_late = st.number_input("Minutes late", min_value=0, max_value=600, value=0, step=1)
            auto_points = calc_late_points(int(minutes_late))

            if minutes_late < 6:
                st.info("Under 6 minutes late → 0 points")
            else:
                extra = (minutes_late - 5) // 10
                st.info(f"Points = 1 + {extra} additional blocks = {auto_points}")

    # -----------------------------
    # Shared Write-Up Form
    # -----------------------------
    with st.form("add_writeup_form", clear_on_submit=True):
        incident_dt = st.date_input("Incident Date", value=date.today())

        manager_notes = st.text_area("Manager Notes")
        secondary_lead_witness = st.text_input("Secondary Lead Witnessing Write-Up")
        corrective_actions = st.text_area("Corrective Actions")
        team_member_comments = st.text_area("Team Member's Comments")

        st.markdown("#### Signatures")
        team_member_signature = st.text_input("Team Member Signature")
        leader_signature = st.text_input("Leader Signature")
        secondary_leader_signature = st.text_input("Secondary Leader Signature")
        signed_dt = st.date_input("Date Signed", value=date.today())

        if chosen_cat_name == "Documented Conversation":
            points_val = 0
            st.caption("Points: 0 (Documented Conversation)")
        else:
            colA, colB = st.columns([1, 1])
            with colA:
                points_override = st.toggle("Override points manually?", value=False)
            with colB:
                points_val = st.number_input(
                    "Points",
                    value=int(auto_points),
                    step=1,
                    disabled=not points_override
                )

        submitted = st.form_submit_button("Save Write-Up")

    if submitted:
        try:
            reason_value = custom_reason if chosen_cat_name == "Documented Conversation" else chosen_rule_name

            final_notes = format_writeup_notes(
                reason=reason_value,
                manager_notes=manager_notes,
                secondary_lead_witness=secondary_lead_witness,
                corrective_actions=corrective_actions,
                team_member_comments=team_member_comments,
                team_member_signature=team_member_signature,
                leader_signature=leader_signature,
                secondary_leader_signature=secondary_leader_signature,
                signed_date=signed_dt,
            )

            add_writeup(
                member_id=member_id,
                category_id=category_id,
                points=int(points_val),
                incident_date=incident_dt,
                notes=final_notes,
                created_by=st.session_state.username,
            )

            # Slack log (still works)
            post_writeup_to_slack(
                member_name=member_name,
                category_name=chosen_cat_name,
                incident_date=incident_dt.isoformat(),
                notes=final_notes,
            )

            st.success("Write-up saved.")
            st.rerun()

        except Exception as e:
            st.error(f"Failed to save write-up: {e}")


def admin_mode():
    st.header("Admin Mode")

    if st.session_state.role != "admin":
        st.error("You do not have access to Admin Mode.")
        return

    st.write(f"Logged in as **{st.session_state.username}** (admin)")

    # -----------------------------
    # Team members
    # -----------------------------
    st.markdown("---")
    st.subheader("Team Members")

    members_all = supabase.from_("team_members").select("id, name, status, created_at").order("name").execute().data or []
    df_all = pd.DataFrame(members_all)
    if not df_all.empty:
        st.dataframe(df_all[["id", "name", "status", "created_at"]], use_container_width=True, hide_index=True)
    else:
        st.info("No members found.")

    st.markdown("### Add Team Member (always starts ACTIVE)")
    with st.form("add_member_form", clear_on_submit=True):
        nm = st.text_input("New team member name")
        if st.form_submit_button("Add Team Member"):
            if nm.strip():
                try:
                    add_team_member(nm)
                    st.success("Team member added as ACTIVE.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding member: {e}")
            else:
                st.warning("Enter a name.")

    st.markdown("---")
    st.subheader("Set Team Member Active / Inactive")

    if members_all:
        label_list = [f"{m['name']} — {m.get('status','active')} ({m['id']})" for m in members_all]
        chosen = st.selectbox("Select team member", label_list, key="admin_member_status_pick")
        chosen_id = chosen.split("(")[-1].replace(")", "").strip()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Mark ACTIVE"):
                set_team_member_status(chosen_id, "active")
                st.success("Member set to ACTIVE.")
                st.rerun()
        with c2:
            if st.button("Mark INACTIVE"):
                set_team_member_status(chosen_id, "inactive")
                st.success("Member set to INACTIVE.")
                st.rerun()

    st.markdown("---")
    st.subheader("Delete Team Member (and ALL write-ups)")
    if members_all:
        del_label = st.selectbox(
            "Select team member to delete",
            [f"{m['name']} ({m['id']})" for m in members_all],
            key="admin_delete_member_pick",
        )
        del_id = del_label.split("(")[-1].replace(")", "").strip()

        if st.button("Delete Team Member + All Write-Ups", type="primary"):
            st.session_state.pending_delete_member_id = del_id

        if st.session_state.pending_delete_member_id:
            st.error(f"Confirm delete team member + ALL writeups: **{st.session_state.pending_delete_member_id}**")
            d1, d2 = st.columns(2)
            with d1:
                if st.button("YES — Delete Member"):
                    delete_team_member(st.session_state.pending_delete_member_id)
                    st.session_state.pending_delete_member_id = None
                    st.success("Deleted member + writeups.")
                    st.session_state.admin_browse_cache = []
                    st.session_state.admin_browse_ids = []
                    st.session_state.admin_browse_index = 0
                    st.rerun()
            with d2:
                if st.button("Cancel"):
                    st.session_state.pending_delete_member_id = None

    # -----------------------------
    # Browse + Delete writeups (chronological)
    # -----------------------------
    st.markdown("---")
    st.subheader("Browse Write-Ups Chronologically (Admin)")

    if st.button("Reload Write-Ups List"):
        st.session_state.admin_browse_cache = []
        st.session_state.admin_browse_ids = []
        st.session_state.admin_browse_index = 0
        st.rerun()

    if not st.session_state.admin_browse_cache:
        all_w = fetch_all_writeups_chronological()
        st.session_state.admin_browse_cache = all_w
        st.session_state.admin_browse_ids = [w["id"] for w in all_w]
        st.session_state.admin_browse_index = 0

    all_w = st.session_state.admin_browse_cache

    if not all_w:
        st.info("No write-ups exist yet.")
    else:
        idx = st.session_state.admin_browse_index
        idx = max(0, min(idx, len(all_w) - 1))
        st.session_state.admin_browse_index = idx

        w = all_w[idx]
        tm = w.get("team_members") or {}
        cat = w.get("writeup_categories") or {}

        st.markdown(f"### {tm.get('name','Unknown')} — {cat.get('name','Unknown')}")
        st.caption(f"Incident: {w.get('incident_date')} | Created: {w.get('created_at')} | ID: {w.get('id')}")
        st.metric("Points", w.get("points", 0))
        st.text_area("Full Notes (includes signatures)", value=w.get("notes") or "", height=260)

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("⬅ Previous", key="admin_prev_w"):
                st.session_state.admin_browse_index = max(0, idx - 1)
                st.rerun()
        with c2:
            st.write(f"**{idx + 1} / {len(all_w)}**")
        with c3:
            if st.button("Next ➡", key="admin_next_w"):
                st.session_state.admin_browse_index = min(len(all_w) - 1, idx + 1)
                st.rerun()

        st.markdown("### Delete This Write-Up")
        if st.button("Delete this write-up", type="primary", key="admin_delete_this_writeup"):
            st.session_state.pending_delete_writeup_id = w["id"]

        if st.session_state.pending_delete_writeup_id:
            st.error(f"Confirm delete write-up: **{st.session_state.pending_delete_writeup_id}**")
            d1, d2 = st.columns(2)
            with d1:
                if st.button("YES — Delete permanently", key="admin_confirm_delete_writeup"):
                    delete_writeup(st.session_state.pending_delete_writeup_id)
                    st.session_state.admin_browse_cache = []
                    st.session_state.admin_browse_ids = []
                    st.session_state.admin_browse_index = max(0, idx - 1)
                    st.session_state.pending_delete_writeup_id = None
                    st.success("Write-up deleted.")
                    st.rerun()
            with d2:
                if st.button("Cancel", key="admin_cancel_delete_writeup"):
                    st.session_state.pending_delete_writeup_id = None

    # -----------------------------
    # User management (roles + disable + delete)
    # -----------------------------
    st.markdown("---")
    st.subheader("User Management")

    users = supabase.from_("users").select("username, role, is_disabled").order("username").execute().data or []
    dfu = pd.DataFrame(users)
    if not dfu.empty:
        df2 = dfu.copy()
        df2["status"] = df2["is_disabled"].apply(lambda x: "DISABLED" if x else "ACTIVE")
        st.dataframe(df2[["username", "role", "status"]], use_container_width=True, hide_index=True)
    else:
        st.info("No users found.")

    st.markdown("### Change User Role")
    if users:
        pick = st.selectbox(
            "Select user",
            [f"{u['username']} ({u.get('role','viewer')})" for u in users],
            key="admin_user_pick_role",
        )
        selected_username = pick.split(" (")[0].strip()
        selected = next((u for u in users if u["username"] == selected_username), None)
        current_role = (selected or {}).get("role") or "viewer"

        new_role = st.selectbox(
            "New role",
            ["viewer", "manager", "admin"],
            index=["viewer", "manager", "admin"].index(current_role) if current_role in ["viewer", "manager", "admin"] else 0,
            key="admin_user_new_role",
        )

        if st.button("Update Role", type="primary", key="admin_role_update_btn"):
            try:
                update_user_role(selected_username, new_role)
                st.success(f"Updated {selected_username} → {new_role}")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update role: {e}")

    st.markdown("---")
    st.markdown("### Disable / Enable User")
    if users:
        pick2 = st.selectbox("Select user", [u["username"] for u in users], key="admin_user_pick_disable")
        selected2 = next((u for u in users if u["username"] == pick2), None)
        is_disabled_now = bool((selected2 or {}).get("is_disabled") or False)

        if pick2 == st.session_state.username:
            st.warning("You can’t disable your own account while logged in.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Disable User", disabled=is_disabled_now, key="admin_disable_user_btn"):
                    try:
                        set_user_disabled(pick2, True)
                        st.success(f"Disabled {pick2}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to disable: {e}")
            with c2:
                if st.button("Enable User", disabled=not is_disabled_now, key="admin_enable_user_btn"):
                    try:
                        set_user_disabled(pick2, False)
                        st.success(f"Enabled {pick2}.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to enable: {e}")

    st.markdown("---")
    st.markdown("### Delete User (permanent)")
    if users:
        del_pick = st.selectbox("Select user to delete", [u["username"] for u in users], key="admin_user_pick_delete")

        if del_pick == st.session_state.username:
            st.warning("You cannot delete your own account while logged in.")
        else:
            if st.button("Delete User", type="primary", key="admin_delete_user_btn"):
                st.session_state.pending_delete_username = del_pick

            if st.session_state.pending_delete_username:
                st.error(f"Confirm delete user: **{st.session_state.pending_delete_username}**")
                d1, d2 = st.columns(2)
                with d1:
                    if st.button("YES — Delete permanently", key="admin_confirm_delete_user"):
                        try:
                            delete_user(st.session_state.pending_delete_username)
                            st.session_state.pending_delete_username = None
                            st.success("User deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete user: {e}")
                with d2:
                    if st.button("Cancel", key="admin_cancel_delete_user"):
                        st.session_state.pending_delete_username = None

    st.markdown("---")
    st.markdown("### Add User")
    with st.form("add_user_form", clear_on_submit=True):
        nu = st.text_input("New username")
        npw = st.text_input("New password", type="password")
        nrole = st.selectbox("Role", ["viewer", "manager", "admin"])
        if st.form_submit_button("Add User"):
            if nu.strip() and npw.strip():
                try:
                    supabase.from_("users").insert(
                        {"username": nu.strip(), "password": npw.strip(), "role": nrole, "is_disabled": False}
                    ).execute()
                    st.success("User added.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding user: {e}")
            else:
                st.warning("Fill in username + password.")


# -----------------------------
# Main
# -----------------------------
if not st.session_state.logged_in:
    login_panel()
    st.stop()

st.sidebar.markdown(f"**Signed in:** {st.session_state.username}\n\n**Role:** {st.session_state.role}")
logout_button()

mode = st.sidebar.selectbox(
    "Select Mode",
    ["Employee Mode", "Manager Mode", "Admin Mode"],
    index=0,
)

if mode == "Employee Mode":
    employee_mode()
elif mode == "Manager Mode":
    manager_mode()
elif mode == "Admin Mode":
    admin_mode()
