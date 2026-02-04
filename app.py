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
SLACK_ALERT_WEBHOOK_URL = os.getenv("SLACK_ALERT_WEBHOOK_URL", "").strip()   # alerts: borderline/suspension/fired
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
# - under 6 minutes: 0
# - 6–14 minutes: 1
# - 15–24: 2
# - 25–34: 3
# etc.
# formula: 0 if <6 else 1 + floor((m - 5)/10)
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
        # don't crash the app if slack fails
        pass


def extract_lead_names_from_notes(notes: str):
    """Best-effort parse of typed signatures from your notes format."""
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
    """Posts each writeup to the writeups channel (date, person, category, reason, lead names)."""
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
    """Only post when entering Borderline/Suspension/Fired."""
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
            {"username": "Lauren", "password": "952426", "role": "admin"}
        ).execute()


def check_login(username: str, password_input: str):
    try:
        user_data = (
            supabase.from_("users")
            .select("password, role")
            .eq("username", username)
            .single()
            .execute()
            .data
        )
        if user_data and password_input == user_data["password"]:
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


def fetch_team_member_name(member_id: str) -> str:
    try:
        d = supabase.from_("team_members").select("name").eq("id", member_id).single().execute().data
        return (d or {}).get("name") or "Unknown"
    except Exception:
        return "Unknown"


def fetch_category_name(category_id: str) -> str:
    try:
        d = supabase.from_("writeup_categories").select("name").eq("id", category_id).single().execute().data
        return (d or {}).get("name") or "Unknown"
    except Exception:
        return "Unknown"


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
    # delete writeups then member
    supabase.from_("writeups").delete().eq("team_member_id", member_id).execute()
    supabase.from_("team_members").delete().eq("id", member_id).execute()


def fetch_all_writeups_chronological():
    # Includes member + category names
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
            st.error("Invalid credentials.")


def logout_button():
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.role = ""
        st.session_state.pending_delete_writeup_id = None
        st.session_state.selected_member_id = None

        # reset admin browse cache
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

    # Cache writeups per member for this page load
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
        standing_choice = st.selectbox(
            "Standing (based on selected quarter points)",
            STANDING_ORDER,
        )

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
        st.dataframe(
            df_q.rename(columns={"quarter": "Quarter", "points": "Points"}),
            hide_index=True,
            use_container_width=True,
        )

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

    # Search box instead of huge dropdown
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
        st.error("No active categories found. Ask an admin to add categories.")
        return

    cat_names = [c["name"] for c in categories]
    cat_map = {c["name"]: c for c in categories}

    st.markdown("---")
    st.subheader("Create Write-Up")

    chosen_cat_name = st.selectbox("Category", cat_names)
    chosen_cat = cat_map[chosen_cat_name]
    category_id = chosen_cat["id"]

    rules = fetch_rules_for_category(category_id)
    if not rules:
        st.warning("No rules found for this category. Add rows to `writeup_rules` in Supabase.")
        return

    rule_labels = [r["rule_name"] for r in rules]
    rule_map = {r["rule_name"]: r for r in rules}

    chosen_rule_name = st.selectbox("Reason / Rule", rule_labels)
    chosen_rule = rule_map[chosen_rule_name]

    auto_points = int(chosen_rule.get("base_points") or 0)

    minutes_late = None
    if chosen_rule.get("is_incremental"):
        minutes_late = st.number_input("Minutes late", min_value=0, max_value=600, value=0, step=1)
        auto_points = calc_late_points(int(minutes_late))

        if minutes_late < 6:
            st.info("Under 6 minutes late → **0 points**")
        else:
            extra = (minutes_late - 5) // 10
            st.info(f"Points = **1** (6–14 min) + **{extra}** (additional 10-min blocks) = **{auto_points}**")

    with st.form("add_writeup_form", clear_on_submit=True):
        incident_dt = st.date_input("Incident Date", value=date.today())

        manager_notes = st.text_area("Manager Notes", placeholder="Factual notes (what happened, impact, expectation).")
        secondary_lead_witness = st.text_input(
            "Secondary Lead Witnessing Write-Up",
            placeholder="Name of secondary lead (or what they witnessed)",
        )
        corrective_actions = st.text_area(
            "Corrective Actions",
            placeholder="What will be done moving forward? Coaching steps? Training? Follow-up plan?",
        )
        team_member_comments = st.text_area("Team Member's Comments", placeholder="Team member response (optional).")

        st.markdown("#### Signatures (typed)")
        team_member_signature = st.text_input("Team Member Signature (type full name)", placeholder="Team member name")
        leader_signature = st.text_input("Leader Signature (type full name)", placeholder="Leader name")
        secondary_leader_signature = st.text_input(
            "Secondary Leader Signature (type full name)", placeholder="Secondary leader name"
        )
        signed_dt = st.date_input("Date Signed", value=date.today())

        colA, colB = st.columns([1, 1])
        with colA:
            points_override = st.toggle("Override points manually?", value=False)
        with colB:
            points_val = st.number_input("Points", value=int(auto_points), step=1, disabled=not points_override)

        submitted = st.form_submit_button("Save Write-Up")

    if submitted:
        try:
            # Standing before (based on quarter totals)
            prev_writeups = fetch_writeups_for_member(member_id)
            q_label = quarter_key(incident_dt)
            prev_q_total = points_in_quarter(prev_writeups, q_label)
            prev_s = standing_label(prev_q_total)

            final_notes = format_writeup_notes(
                reason=chosen_rule_name,
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

            # Standing after
            new_writeups = fetch_writeups_for_member(member_id)
            new_q_total = points_in_quarter(new_writeups, q_label)
            new_s = standing_label(new_q_total)

            # Slack: writeup log channel
            member_nm = member_name
            cat_nm = chosen_cat_name
            post_writeup_to_slack(
                member_name=member_nm,
                category_name=cat_nm,
                incident_date=incident_dt.isoformat(),
                notes=final_notes,
            )

            # Slack: alerts channel for entering borderline/suspension/fired
            maybe_post_standing_alert(
                member_name=member_nm,
                quarter_label=q_label,
                prev_label=prev_s,
                new_label=new_s,
                q_points=new_q_total,
            )

            st.success("Write-up saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save write-up: {e}")

    st.markdown("---")
    st.subheader("Recent Write-Ups for Selected Member")
    writeups = fetch_writeups_for_member(member_id)
    if not writeups:
        st.info("No write-ups yet for this person.")
        return

    rows = []
    for w in writeups:
        cat = w.get("writeup_categories") or {}
        cat_name = cat.get("name") if isinstance(cat, dict) else None
        rows.append(
            {
                "Incident Date": w.get("incident_date"),
                "Category": cat_name,
                "Points": w.get("points"),
                "Created By": w.get("created_by"),
                "Writeup ID": w.get("id"),
            }
        )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("View Full Write-Up Details (including signatures)", expanded=False):
        ids = [w["id"] for w in writeups]
        chosen_id = st.selectbox("Select Writeup ID", ids, key="mgr_view_writeup_id")
        chosen = next((w for w in writeups if w["id"] == chosen_id), None)
        if chosen:
            st.text_area("Full Write-Up Details", value=chosen.get("notes") or "", height=260)


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

    # Optional: delete team member
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

                    # Refresh browse cache too
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

    # Reload button
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

        st.markdown("### 🗑 Delete This Write-Up")

        if st.button("Delete this write-up", type="primary", key="admin_delete_this_writeup"):
            st.session_state.pending_delete_writeup_id = w["id"]

        if st.session_state.pending_delete_writeup_id:
            st.error(f"Confirm delete write-up: **{st.session_state.pending_delete_writeup_id}**")
            d1, d2 = st.columns(2)
            with d1:
                if st.button("YES — Delete permanently", key="admin_confirm_delete_writeup"):
                    delete_writeup(st.session_state.pending_delete_writeup_id)

                    # refresh cache
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
    # User management
    # -----------------------------
    st.markdown("---")
    st.subheader("User Management")

    users = supabase.from_("users").select("username, role").order("username").execute().data or []
    dfu = pd.DataFrame(users)
    if not dfu.empty:
        st.dataframe(dfu, use_container_width=True, hide_index=True)

    with st.form("add_user_form", clear_on_submit=True):
        nu = st.text_input("New username")
        npw = st.text_input("New password", type="password")
        nrole = st.selectbox("Role", ["viewer", "manager", "admin"])
        if st.form_submit_button("Add User"):
            if nu.strip() and npw.strip():
                try:
                    supabase.from_("users").insert(
                        {"username": nu.strip(), "password": npw.strip(), "role": nrole}
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

st.sidebar.write(f"Signed in: **{st.session_state.username}** ({st.session_state.role})")
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
