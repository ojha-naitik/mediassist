from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response  # type: ignore
from werkzeug.security import generate_password_hash, check_password_hash  # type: ignore
from functools import wraps
import mysql.connector
import os
import secrets
import io
import qrcode  # type: ignore
import ai_assistant as ai   # Ollama chat + safety rules (backend/ai_assistant.py)
from datetime import date, datetime, timedelta

base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, '..', 'templates')
static_dir = os.path.join(template_dir, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
# secrets come from environment variables so they are never committed to GitHub
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# NOTE: this is a brand new database name, separate from the original
# `healthcare_db`. It's created fresh by the updated healthcare_db.sql,
# so your old database and its data are left completely untouched.
DB_NAME = "mediassist_care_db"


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=DB_NAME
    )


# ---------------------------------------------------------
# small helper functions
# ---------------------------------------------------------
def get_patient_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT patient_id FROM PATIENT_PROFILE WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def get_doctor_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT doctor_id FROM DOCTOR_PROFILE WHERE user_id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def get_or_create_qr_token(patient_id):
    """
    Every patient has one unique, hard-to-guess token stored on their
    PATIENT_PROFILE row. It's created the first time it's needed and then
    reused, so a patient's QR code stays the same until they regenerate it.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT qr_token FROM PATIENT_PROFILE WHERE patient_id = %s", (patient_id,))
        row = cursor.fetchone()
        token = row[0] if row else None
        if not token:
            token = secrets.token_urlsafe(24)
            cursor.execute(
                "UPDATE PATIENT_PROFILE SET qr_token = %s WHERE patient_id = %s",
                (token, patient_id)
            )
            conn.commit()
        return token
    finally:
        cursor.close()
        conn.close()


def start_session(user, registration_no=None):
    """Store the logged-in user's details in the session (used by both login routes)."""
    session.clear()
    session["user_id"] = user["user_id"]
    session["name"] = user["name"]
    session["email"] = user["email"]
    session["role"] = user["role"]

    # stash the profile id too so we don't have to look it up on every request
    if user["role"] == "doctor":
        session["doctor_id"] = get_doctor_id(user["user_id"])
        session["registration_no"] = registration_no
    else:
        session["patient_id"] = get_patient_id(user["user_id"])


def home_for_role():
    """Where a logged-in user should land."""
    if session.get("role") == "doctor":
        return redirect(url_for("doctor_dashboard"))
    return redirect(url_for("dashboard"))


def login_required(role=None):
    """
    Decorator for protected pages.
      @login_required()           -> any logged-in user
      @login_required("patient")  -> patients only (doctors are sent to their own dashboard)
      @login_required("doctor")   -> doctors only  (patients are sent to their own dashboard)
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                # remember where they were headed (e.g. a scanned QR report link)
                # so login can send them straight back after they sign in
                if request.method == "GET":
                    session["next_url"] = request.path
                flash("Please login first.")
                return redirect(url_for("home"))
            if role and session.get("role") != role:
                return home_for_role()
            return view(*args, **kwargs)
        return wrapped
    return decorator


def redirect_after_login(default_endpoint):
    """After a successful login, send the user back to whatever page they were
    trying to reach (e.g. a scanned QR code report link) instead of always the
    default dashboard - but only if that page actually belongs to their role."""
    next_url = session.pop("next_url", None)
    if next_url and next_url.startswith("/report/") and session.get("role") == "doctor":
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


# ---------------------------------------------------------
# auth
# ---------------------------------------------------------
@app.route("/", methods=['GET', 'POST'])
def home():
    if "user_id" in session:
        return home_for_role()
    return render_template("login.html")


@app.route("/signup", methods=["POST"])
def signup():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password")

    if not name or not email or not password:
        flash("Name, email and password are required.")
        return redirect(url_for("home"))

    # Self sign-up ALWAYS creates a patient account. The role is never read from the
    # form, so nobody can register themselves as a doctor/admin by editing the request.
    # Doctor accounts are created by the hospital (registration no. + password in the DB).
    role = "patient"

    hashed_password = generate_password_hash(password)  # werkzeug

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id FROM USER WHERE email = %s", (email,))
        if cursor.fetchone():
            flash("An account with this email already exists. Please login.")
            return redirect(url_for("home"))

        cursor.execute(
            "INSERT INTO USER (name, email, password, role) VALUES (%s, %s, %s, %s)",
            (name, email, hashed_password, role)
        )
        new_user_id = cursor.lastrowid

        # patient details (height / weight / blood group) are filled in later
        cursor.execute(
            "INSERT INTO PATIENT_PROFILE (user_id, height, weight, blood_group) "
            "VALUES (%s, %s, %s, %s)",
            (new_user_id, None, None, None)
        )

        conn.commit()
        flash("Account created successfully. Please login.")
    finally:
        cursor.close()
        conn.close()

    # send the new user back to the login page (not the dashboard - they aren't logged in yet)
    return redirect(url_for("home"))


@app.route("/login", methods=["POST"])
def login():
    """Patient login: email + password."""
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM USER WHERE email = %s", (email,))
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if user and check_password_hash(user["password"], password):
        if user["role"] != "patient":
            flash("This is a doctor account. Please use the Doctor Login tab with your registration number.")
            return redirect(url_for("home"))
        start_session(user)
        return redirect_after_login("dashboard")

    flash("Invalid email or password.")
    return redirect(url_for("home"))


@app.route("/doctor/login", methods=["POST"])
def doctor_login():
    """Doctor login: registration number + password (both stored in the database)."""
    registration_no = (request.form.get("registration_no") or "").strip().upper()
    password = request.form.get("password") or ""

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT u.*, d.registration_no FROM DOCTOR_PROFILE d "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE d.registration_no = %s AND u.role = 'doctor'",
            (registration_no,)
        )
        doctor = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if doctor and check_password_hash(doctor["password"], password):
        start_session(doctor, registration_no=doctor["registration_no"])
        return redirect_after_login("doctor_dashboard")

    flash("Invalid registration number or password.")
    return redirect(url_for("home") + "#doctor")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------------------------------------------------
# patient dashboard
# ---------------------------------------------------------
def greeting_for_now():
    hour = datetime.now().hour
    if hour < 12:
        return "Good Morning"
    if hour < 17:
        return "Good Afternoon"
    return "Good Evening"


def health_score(cursor, patient_id):
    """
    Simple, transparent score out of 100 (last 7 days):
      50 pts  active minutes vs the weekly goal (WEEKLY_GOAL_MINUTES)
      50 pts  how many of the 7 days have at least one meal logged
    """
    since = date.today() - timedelta(days=6)
    cursor.execute(
        "SELECT COALESCE(SUM(duration), 0) FROM FITNESS WHERE patient_id = %s AND date >= %s",
        (patient_id, since)
    )
    minutes = int(cursor.fetchone()[0])
    cursor.execute(
        "SELECT COUNT(DISTINCT date) FROM MEALS WHERE patient_id = %s AND date >= %s",
        (patient_id, since)
    )
    logged_days = int(cursor.fetchone()[0])

    score = round(min(minutes / WEEKLY_GOAL_MINUTES, 1) * 50 + (logged_days / 7) * 50)
    if score >= 80:
        label = "Excellent"
    elif score >= 60:
        label = "Good"
    elif score >= 40:
        label = "Fair"
    else:
        label = "Needs attention"
    return score, label


@app.route("/dashboard")
@login_required("patient")
def dashboard():
    patient_id = session.get("patient_id")
    stats = {"upcoming_appointments": 0, "health_records": 0, "medicine_reminders": 0,
             "health_score": 0, "health_label": "No data yet"}
    todays_appointments, medicine_reminders, recent_records = [], [], []
    report_url = None

    if patient_id:
        report_url = url_for("patient_report", token=get_or_create_qr_token(patient_id), _external=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        dict_cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM APPOINTMENT WHERE patient_id = %s AND date_time >= NOW() "
                "AND status IN ('pending', 'confirmed')",
                (patient_id,)
            )
            stats["upcoming_appointments"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM PRESCRIPTION WHERE patient_id = %s", (patient_id,))
            stats["health_records"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM MEDICINE m "
                "JOIN PRESCRIPTION p ON m.prescription_id = p.prescription_id "
                "WHERE p.patient_id = %s",
                (patient_id,)
            )
            stats["medicine_reminders"] = cursor.fetchone()[0]

            stats["health_score"], stats["health_label"] = health_score(cursor, patient_id)

            # today's schedule = today's appointments that are not cancelled
            dict_cursor.execute(
                "SELECT a.date_time, a.status, u.name AS doctor_name, d.specialization "
                "FROM APPOINTMENT a "
                "JOIN DOCTOR_PROFILE d ON a.doctor_id = d.doctor_id "
                "JOIN USER u ON d.user_id = u.user_id "
                "WHERE a.patient_id = %s AND DATE(a.date_time) = CURDATE() AND a.status != 'cancelled' "
                "ORDER BY a.date_time",
                (patient_id,)
            )
            todays_appointments = dict_cursor.fetchall()

            # latest medicines from the most recent prescriptions
            dict_cursor.execute(
                "SELECT m.name, m.dosage, m.frequency FROM MEDICINE m "
                "JOIN PRESCRIPTION p ON m.prescription_id = p.prescription_id "
                "WHERE p.patient_id = %s ORDER BY p.date DESC, m.medicine_id LIMIT 2",
                (patient_id,)
            )
            medicine_reminders = dict_cursor.fetchall()

            dict_cursor.execute(
                "SELECT p.prescription_id, p.date, u.name AS doctor_name "
                "FROM PRESCRIPTION p "
                "JOIN DOCTOR_PROFILE d ON p.doctor_id = d.doctor_id "
                "JOIN USER u ON d.user_id = u.user_id "
                "WHERE p.patient_id = %s ORDER BY p.date DESC LIMIT 3",
                (patient_id,)
            )
            recent_records = dict_cursor.fetchall()
        finally:
            dict_cursor.close()
            cursor.close()
            conn.close()

    return render_template(
        "dashboard.html",
        name=session.get("name"),
        email=session.get("email"),
        role=session.get("role"),
        greeting=greeting_for_now(),
        stats=stats,
        todays_appointments=todays_appointments,
        medicine_reminders=medicine_reminders,
        recent_records=recent_records,
        report_url=report_url
    )


@app.route("/api/timeline")
@login_required("patient")
def api_timeline():
    """
    Data for the dashboard timeline graph: for each of the last N days
    calories eaten (MEALS), calories burned (FITNESS) and active minutes (FITNESS).
    """
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        days = 7
    if days not in (7, 30, 90):
        days = 7

    patient_id = session.get("patient_id")
    start = date.today() - timedelta(days=days - 1)

    intake, burned, minutes = {}, {}, {}
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT date, COALESCE(SUM(calories), 0) FROM MEALS "
            "WHERE patient_id = %s AND date >= %s GROUP BY date",
            (patient_id, start)
        )
        for d, c in cursor.fetchall():
            intake[d] = int(c)

        cursor.execute(
            "SELECT date, COALESCE(SUM(calories), 0), COALESCE(SUM(duration), 0) FROM FITNESS "
            "WHERE patient_id = %s AND date >= %s GROUP BY date",
            (patient_id, start)
        )
        for d, c, m in cursor.fetchall():
            burned[d] = int(c)
            minutes[d] = int(m)
    finally:
        cursor.close()
        conn.close()

    # A day with nothing logged is sent as null (a gap in the graph) instead of 0,
    # so days before the user started tracking don't look like "0 calories".
    labels, series_in, series_out, series_min = [], [], [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.isoformat())
        series_in.append(intake.get(d))                       # None when no meal logged
        if d in burned:
            series_out.append(burned[d])
            series_min.append(minutes[d])
        elif d in intake:                                     # tracked day, no workout = rest day
            series_out.append(0)
            series_min.append(0)
        else:
            series_out.append(None)
            series_min.append(None)

    return jsonify({
        "days": days,
        "labels": labels,
        "intake": series_in,
        "burned": series_out,
        "minutes": series_min
    })


# ---------------------------------------------------------
# AI assistant  (local Ollama model - see backend/ai_assistant.py)
# Works for both patients and doctors; the ROLE comes from the
# login session (never from the browser), and decides which
# system prompt / boundaries / data the model gets.
# ---------------------------------------------------------
@app.route("/ai-assistant")
@login_required()
def ai_assistant():
    return render_template("ai-assistant.html", ai_model=ai.OLLAMA_MODEL)


@app.route("/api/ai-assistant/status")
@login_required()
def ai_status():
    online, model_ready = ai.ollama_status()
    return jsonify({"online": online, "model_ready": model_ready, "model": ai.OLLAMA_MODEL})


@app.route("/api/ai-assistant/chat", methods=["POST"])
@login_required()
def ai_chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str):
        message = ""
    role = "doctor" if session.get("role") == "doctor" else "patient"

    if ai.rate_limited(session["user_id"]):
        return jsonify({"reply": ai.RATE_LIMIT_REPLY, "blocked": True}), 429

    # 1. code-level boundaries: emergencies, injection, off-topic, too long...
    blocked_reply, flags = ai.check_message(message, role)
    if blocked_reply:
        return jsonify({"reply": blocked_reply, "blocked": True})

    # 2. build the role-specific prompt with ONLY this user's own data
    conn = None
    try:
        conn = get_db_connection()
        if role == "doctor":
            app_data = ai.build_doctor_context(conn, session.get("doctor_id"))
        else:
            app_data = ai.build_patient_context(conn, session.get("patient_id"))
    except Exception:
        app.logger.exception("AI assistant: could not load user context")
        app_data = "(the user's data could not be loaded - do not guess any personal details)"
    finally:
        if conn:
            conn.close()

    system_prompt = ai.build_system_prompt(role, session.get("name"), app_data, flags)
    history = ai.clean_history(data.get("history"))

    # 3. ask the local Ollama model
    try:
        reply = ai.ollama_chat(system_prompt, history, message.strip(), role)
    except ai.OllamaError as e:
        app.logger.warning("AI assistant: Ollama error (%s): %s", e.kind, e)
        status = 503 if e.kind in ("unavailable", "model_missing") else 504 if e.kind == "timeout" else 502
        return jsonify({"reply": ai.ERROR_REPLIES.get(e.kind, ai.ERROR_REPLIES["bad_response"]),
                        "error": e.kind}), status

    return jsonify({"reply": ai.finalize_reply(reply, role)})


# ---------------------------------------------------------
# appointments  -> APPOINTMENT table (patient side)
# ---------------------------------------------------------
@app.route("/appointments")
@login_required("patient")
def appointments():
    patient_id = session.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT a.appointment_id, a.date_time, a.status, "
            "u.name AS doctor_name, d.specialization "
            "FROM APPOINTMENT a "
            "JOIN DOCTOR_PROFILE d ON a.doctor_id = d.doctor_id "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE a.patient_id = %s "
            "ORDER BY a.date_time DESC",
            (patient_id,)
        )
        appointment_list = cursor.fetchall()

        cursor.execute(
            "SELECT d.doctor_id, u.name, d.specialization "
            "FROM DOCTOR_PROFILE d JOIN USER u ON d.user_id = u.user_id "
            "ORDER BY u.name"
        )
        doctors = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    stats = {
        "upcoming": sum(1 for a in appointment_list if a["status"] in ("pending", "confirmed")),
        "confirmed": sum(1 for a in appointment_list if a["status"] == "confirmed"),
        "pending": sum(1 for a in appointment_list if a["status"] == "pending"),
        "completed": sum(1 for a in appointment_list if a["status"] == "completed"),
    }

    return render_template(
        "appointments.html",
        appointments=appointment_list,
        doctors=doctors,
        stats=stats,
        today=date.today()
    )


@app.route("/appointments/book", methods=["POST"])
@login_required("patient")
def book_appointment():
    patient_id = session.get("patient_id")
    doctor_id = request.form.get("doctor_id")
    appt_date = request.form.get("date")
    appt_time = request.form.get("time")

    try:
        date_time = datetime.strptime(f"{appt_date} {appt_time}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        flash("Please choose a valid date and time.")
        return redirect(url_for("appointments"))

    if date_time < datetime.now():
        flash("Please choose a date and time in the future.")
        return redirect(url_for("appointments"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT doctor_id FROM DOCTOR_PROFILE WHERE doctor_id = %s", (doctor_id,))
        if not cursor.fetchone():
            flash("Selected doctor was not found.")
            return redirect(url_for("appointments"))

        # don't allow two active bookings for the same doctor at the same time
        cursor.execute(
            "SELECT appointment_id FROM APPOINTMENT "
            "WHERE doctor_id = %s AND date_time = %s AND status IN ('pending', 'confirmed')",
            (doctor_id, date_time)
        )
        if cursor.fetchone():
            flash("That slot is already taken. Please pick another time.")
            return redirect(url_for("appointments"))

        cursor.execute(
            "INSERT INTO APPOINTMENT (patient_id, doctor_id, date_time, status) "
            "VALUES (%s, %s, %s, 'pending')",
            (patient_id, doctor_id, date_time)
        )
        conn.commit()
        flash("Appointment requested. It will be confirmed once the doctor approves it.")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("appointments"))


@app.route("/appointments/cancel/<int:appointment_id>", methods=["POST"])
@login_required("patient")
def cancel_appointment(appointment_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE APPOINTMENT SET status = 'cancelled' "
            "WHERE appointment_id = %s AND patient_id = %s AND status IN ('pending', 'confirmed')",
            (appointment_id, session.get("patient_id"))
        )
        conn.commit()
        if cursor.rowcount:
            flash("Appointment cancelled.")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("appointments"))


# ---------------------------------------------------------
# doctor dashboard  -> approve / decline / complete appointments
# ---------------------------------------------------------
@app.route("/doctor/dashboard")
@login_required("doctor")
def doctor_dashboard():
    doctor_id = session.get("doctor_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT d.specialization, d.qualification, d.registration_no "
            "FROM DOCTOR_PROFILE d WHERE d.doctor_id = %s",
            (doctor_id,)
        )
        profile = cursor.fetchone() or {}

        cursor.execute(
            "SELECT a.appointment_id, a.date_time, a.status, "
            "u.name AS patient_name, u.email AS patient_email, u.phone AS patient_phone, "
            "TIMESTAMPDIFF(YEAR, u.date_of_birth, CURDATE()) AS patient_age "
            "FROM APPOINTMENT a "
            "JOIN PATIENT_PROFILE p ON a.patient_id = p.patient_id "
            "JOIN USER u ON p.user_id = u.user_id "
            "WHERE a.doctor_id = %s "
            "ORDER BY FIELD(a.status, 'pending', 'confirmed', 'completed', 'cancelled'), a.date_time",
            (doctor_id,)
        )
        all_appointments = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(DISTINCT patient_id) AS total FROM APPOINTMENT WHERE doctor_id = %s",
            (doctor_id,)
        )
        total_patients = cursor.fetchone()["total"]
    finally:
        cursor.close()
        conn.close()

    today = date.today()
    pending = [a for a in all_appointments if a["status"] == "pending"]
    todays = [a for a in all_appointments
              if a["status"] == "confirmed" and a["date_time"].date() == today]

    stats = {
        "pending": len(pending),
        "today": len(todays),
        "confirmed": sum(1 for a in all_appointments if a["status"] == "confirmed"),
        "patients": total_patients,
    }

    return render_template(
        "doctor-dashboard.html",
        profile=profile,
        greeting=greeting_for_now(),
        stats=stats,
        pending=pending,
        others=[a for a in all_appointments if a["status"] != "pending"],
    )


# what a doctor may do:  action -> (new status, statuses it is allowed from, message)
DOCTOR_ACTIONS = {
    "approve":  ("confirmed", ("pending",), "Appointment approved."),
    "decline":  ("cancelled", ("pending", "confirmed"), "Appointment declined."),
    "complete": ("completed", ("confirmed",), "Appointment marked as completed."),
}


@app.route("/doctor/appointments/<int:appointment_id>/<action>", methods=["POST"])
@login_required("doctor")
def doctor_appointment_action(appointment_id, action):
    if action not in DOCTOR_ACTIONS:
        flash("Unknown action.")
        return redirect(url_for("doctor_dashboard"))

    new_status, allowed_from, message = DOCTOR_ACTIONS[action]
    placeholders = ", ".join(["%s"] * len(allowed_from))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # doctor_id in the WHERE clause = a doctor can only touch their OWN appointments
        cursor.execute(
            "UPDATE APPOINTMENT SET status = %s "
            f"WHERE appointment_id = %s AND doctor_id = %s AND status IN ({placeholders})",
            (new_status, appointment_id, session.get("doctor_id"), *allowed_from)
        )
        conn.commit()
        flash(message if cursor.rowcount else "That appointment can no longer be changed.")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("doctor_dashboard"))


# ---------------------------------------------------------
# health records  -> PRESCRIPTION table
# ---------------------------------------------------------
@app.route("/health-records")
@login_required("patient")
def health_records():
    patient_id = session.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT p.prescription_id, p.date, p.file_url, u.name AS doctor_name, "
            "(SELECT COUNT(*) FROM MEDICINE m WHERE m.prescription_id = p.prescription_id) AS medicine_count "
            "FROM PRESCRIPTION p "
            "JOIN DOCTOR_PROFILE d ON p.doctor_id = d.doctor_id "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE p.patient_id = %s "
            "ORDER BY p.date DESC",
            (patient_id,)
        )
        records = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("health-records.html", records=records)


# ---------------------------------------------------------
# patient QR code  -> shareable link to the full medical report
# ---------------------------------------------------------
@app.route("/qr-code.png")
@login_required("patient")
def patient_qr_code():
    """Renders the patient's personal QR code as a PNG image on the fly.
    The QR code encodes the public link to their /report/<token> page."""
    patient_id = session.get("patient_id")
    token = get_or_create_qr_token(patient_id)
    report_url = url_for("patient_report", token=token, _external=True)

    img = qrcode.make(report_url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    response = Response(buf.getvalue(), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store"  # always reflect the current token
    return response


@app.route("/qr-code/regenerate", methods=["POST"])
@login_required("patient")
def regenerate_qr_code():
    """Issues a brand new token, instantly invalidating the old QR code/link
    (anyone who had the old one, or a screenshot of it, can no longer use it)."""
    patient_id = session.get("patient_id")
    new_token = secrets.token_urlsafe(24)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE PATIENT_PROFILE SET qr_token = %s WHERE patient_id = %s",
            (new_token, patient_id)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    flash("Your QR code has been refreshed. The old QR code will no longer work.")
    return redirect(url_for("dashboard"))


@app.route("/report/<token>")
@login_required("doctor")
def patient_report(token):
    """Full medical report for one patient, reached by a doctor scanning that
    patient's QR code (or opening their shared link). Only logged-in doctors
    can view it - the token alone isn't enough."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT p.patient_id, p.height, p.weight, p.blood_group, "
            "u.name, u.email, u.phone, u.date_of_birth, u.gender "
            "FROM PATIENT_PROFILE p JOIN USER u ON p.user_id = u.user_id "
            "WHERE p.qr_token = %s",
            (token,)
        )
        patient = cursor.fetchone()

        if not patient:
            flash("This QR code / link is invalid or has been refreshed by the patient.")
            return redirect(url_for("doctor_dashboard"))

        patient_id = patient["patient_id"]
        today = date.today()
        if patient.get("date_of_birth"):
            dob = patient["date_of_birth"]
            patient["age"] = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        else:
            patient["age"] = None

        cursor.execute(
            "SELECT p.prescription_id, p.date, u.name AS doctor_name, d.specialization "
            "FROM PRESCRIPTION p "
            "JOIN DOCTOR_PROFILE d ON p.doctor_id = d.doctor_id "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE p.patient_id = %s ORDER BY p.date DESC",
            (patient_id,)
        )
        prescriptions = cursor.fetchall()
        for pres in prescriptions:
            cursor.execute(
                "SELECT name, dosage, frequency, duration FROM MEDICINE "
                "WHERE prescription_id = %s",
                (pres["prescription_id"],)
            )
            pres["medicines"] = cursor.fetchall()

        cursor.execute(
            "SELECT a.date_time, a.status, u.name AS doctor_name, d.specialization "
            "FROM APPOINTMENT a "
            "JOIN DOCTOR_PROFILE d ON a.doctor_id = d.doctor_id "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE a.patient_id = %s ORDER BY a.date_time DESC LIMIT 10",
            (patient_id,)
        )
        appointment_history = cursor.fetchall()

        cursor.execute(
            "SELECT exercise, duration, calories, date FROM FITNESS "
            "WHERE patient_id = %s ORDER BY date DESC LIMIT 10",
            (patient_id,)
        )
        fitness_history = cursor.fetchall()

        cursor.execute(
            "SELECT food, calories, date FROM MEALS "
            "WHERE patient_id = %s ORDER BY date DESC LIMIT 10",
            (patient_id,)
        )
        meal_history = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "patient-report.html",
        patient=patient,
        prescriptions=prescriptions,
        appointment_history=appointment_history,
        fitness_history=fitness_history,
        meal_history=meal_history,
    )


@app.route("/report/<token>/ai-summary", methods=["POST"])
@login_required("doctor")
def patient_report_ai_summary(token):
    """'Summarize with AI' button on the patient report page (doctors only).
    The record is re-read from the database using the QR token - nothing the
    browser sends is put in the prompt."""
    if ai.rate_limited(session["user_id"]):
        return jsonify({"reply": ai.RATE_LIMIT_REPLY}), 429

    conn = get_db_connection()
    try:
        record = ai.build_report_context(conn, token)
    finally:
        conn.close()
    if record is None:
        return jsonify({"reply": "This QR code / link is invalid or has been refreshed by the patient."}), 404

    try:
        reply = ai.ollama_chat(ai.REPORT_SUMMARY_PROMPT, [], record + "\n\nSummarise this record now.",
                               "doctor", max_tokens=600)
    except ai.OllamaError as e:
        app.logger.warning("AI summary: Ollama error (%s): %s", e.kind, e)
        status = 503 if e.kind in ("unavailable", "model_missing") else 504 if e.kind == "timeout" else 502
        return jsonify({"reply": ai.ERROR_REPLIES.get(e.kind, ai.ERROR_REPLIES["bad_response"]),
                        "error": e.kind}), status
    return jsonify({"reply": ai.finalize_reply(reply, "doctor"), "model": ai.OLLAMA_MODEL})


# ---------------------------------------------------------
# medicine logs  -> MEDICINE table (via PRESCRIPTION)
# ---------------------------------------------------------
@app.route("/medicine-logs")
@login_required("patient")
def medicine_logs():
    patient_id = session.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT m.medicine_id, m.name, m.dosage, m.frequency, m.duration, "
            "p.prescription_id, p.date AS prescription_date, u.name AS doctor_name "
            "FROM MEDICINE m "
            "JOIN PRESCRIPTION p ON m.prescription_id = p.prescription_id "
            "JOIN DOCTOR_PROFILE d ON p.doctor_id = d.doctor_id "
            "JOIN USER u ON d.user_id = u.user_id "
            "WHERE p.patient_id = %s "
            "ORDER BY p.date DESC",
            (patient_id,)
        )
        medicines = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("medicine-logs.html", medicines=medicines)


# ---------------------------------------------------------
# food logs  -> MEALS table
# ---------------------------------------------------------
@app.route("/food-logs")
@login_required("patient")
def food_logs():
    patient_id = session.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT meal_id, food, calories, date FROM MEALS "
            "WHERE patient_id = %s ORDER BY date DESC, meal_id DESC",
            (patient_id,)
        )
        meals = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    today = date.today()
    todays_meals = [m for m in meals if m["date"] == today]

    # average daily calories over the last 7 days that have at least one meal logged
    week_start = today - timedelta(days=6)
    per_day = {}
    for m in meals:
        if m["date"] >= week_start:
            per_day[m["date"]] = per_day.get(m["date"], 0) + (m["calories"] or 0)
    weekly_avg = round(sum(per_day.values()) / len(per_day)) if per_day else 0

    stats = {
        "today_calories": sum((m["calories"] or 0) for m in todays_meals),
        "meals_today": len(todays_meals),
        "weekly_avg": weekly_avg,
    }

    return render_template("food-logs.html", meals=meals, stats=stats, today=today)


@app.route("/food-logs/add", methods=["POST"])
@login_required("patient")
def add_meal():
    food = (request.form.get("food") or "").strip()
    calories = request.form.get("calories")
    meal_date = request.form.get("date")

    if not food or not meal_date:
        flash("Food and date are required.")
        return redirect(url_for("food_logs"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO MEALS (patient_id, food, calories, date) VALUES (%s, %s, %s, %s)",
            (session.get("patient_id"), food, calories or 0, meal_date)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("food_logs"))


# ---------------------------------------------------------
# fitness  -> FITNESS table
# ---------------------------------------------------------
WEEKLY_GOAL_MINUTES = 150


@app.route("/fitness")
@login_required("patient")
def fitness():
    patient_id = session.get("patient_id")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT fitness_id, exercise, duration, calories, date FROM FITNESS "
            "WHERE patient_id = %s ORDER BY date DESC, fitness_id DESC",
            (patient_id,)
        )
        workouts = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    today = date.today()
    todays_workouts = [w for w in workouts if w["date"] == today]
    week_start = today - timedelta(days=6)
    week_minutes = sum((w["duration"] or 0) for w in workouts if w["date"] >= week_start)
    goal_percent = min(100, round((week_minutes / WEEKLY_GOAL_MINUTES) * 100)) if week_minutes else 0

    stats = {
        "today_calories": sum((w["calories"] or 0) for w in todays_workouts),
        "today_minutes": sum((w["duration"] or 0) for w in todays_workouts),
        "goal_percent": goal_percent,
    }

    return render_template("fitness.html", workouts=workouts, stats=stats, today=today)


@app.route("/fitness/add", methods=["POST"])
@login_required("patient")
def add_workout():
    exercise = (request.form.get("exercise") or "").strip()
    duration = request.form.get("duration")
    calories = request.form.get("calories")
    workout_date = request.form.get("date")

    if not exercise or not workout_date:
        flash("Exercise and date are required.")
        return redirect(url_for("fitness"))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO FITNESS (patient_id, exercise, duration, calories, date) "
            "VALUES (%s, %s, %s, %s, %s)",
            (session.get("patient_id"), exercise, duration or 0, calories or 0, workout_date)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("fitness"))


if __name__ == "__main__":
    app.run(debug=True)
