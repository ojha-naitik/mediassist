# MediAssist – Milestone 3

Flask + MySQL healthcare tracker with separate **patient** and **doctor** logins.

## Run it
```bash
pip install -r requirements.txt
mysql -u root -p < healthcare_db.sql      # creates the NEW database mediassist_care_db + sample data (re-run to reset)
                                           # your old `healthcare_db` is untouched - this is a different DB name
cd backend
python app.py                             # open http://127.0.0.1:5000
```
Database password and secret key are read from environment variables (see `.env.example`):
```powershell
# Windows PowerShell
$env:DB_PASSWORD="your-mysql-password"
$env:SECRET_KEY="any-long-random-string"
python app.py
```
```bash
# macOS / Linux
export DB_PASSWORD="your-mysql-password" SECRET_KEY="any-long-random-string"
python app.py
```
`DB_HOST` and `DB_USER` are optional (defaults `localhost` / `root`).

## Sample logins
| Who | Login tab | ID | Password |
|---|---|---|---|
| Dr. Sneha Verma (General Physician) | Doctor Login | `MED-1001` | `Sneha@1001` |
| Dr. Rohit Sharma (Cardiologist) | Doctor Login | `MED-1002` | `Rohit@1002` |
| Dr. Anjali Mehta (Dermatologist) | Doctor Login | `MED-1003` | `Anjali@1003` |
| Dr. Vikram Singh (Orthopedic) | Doctor Login | `MED-1004` | `Vikram@1004` |
| Aarav Patel (patient, lots of data) | Login | `aarav@demo.com` | `Patient@123` |
| Priya Nair (patient) | Login | `priya@demo.com` | `Patient@456` |

Sample dates are relative to the day you import the SQL, so the timeline graph is always current.

## How appointments work
1. Patient books a doctor -> status **pending** ("Awaiting doctor approval").
2. Doctor logs in -> **Doctor Dashboard** -> **Approve** (confirmed) or **Decline** (cancelled).
3. After the visit the doctor clicks **Mark completed**. Patients may cancel pending/confirmed bookings.

## What's where
| Path | Purpose |
|---|---|
| `healthcare_db.sql` | schema (commented) + sample data, database name **`mediassist_care_db`** |
| `backend/app.py` | all routes: auth, dashboards, appointments, logs, `/api/timeline`, `/database`, QR code + report |
| `templates/dashboard.html` | patient dashboard (profile menu, live timeline graph, "Share with a Doctor" QR section) |
| `templates/doctor-dashboard.html` | doctor dashboard (approve / decline / complete, look up a patient by QR/code) |
| `templates/patient-report.html` | full medical report a doctor sees after scanning a patient's QR code |
| `backend/ai_assistant.py` | Ollama client + AI safety rules (prompts, guardrails, rate limit) |
| `templates/ai-assistant.html` | AI chat page for patients and doctors (talks to `/api/ai-assistant/chat`) |
| `templates/db-viewer.html` | read-only view of every table (`/database`) |
| `templates/_profile_menu.html` | top-right profile menu (name, email, role, logout) |
| `templates/base_app.html` | shared layout for doctor / AI / database / report pages |

## Patient QR code -> full medical report
Every patient gets a unique, private QR code, shown in the **"Share with a Doctor"** section
of their dashboard (click **View My QR Code**).

* The QR code encodes a link to `/report/<token>`, where `token` is a long random
  code stored on that patient's `PATIENT_PROFILE` row (`qr_token`).
* Only a **logged-in doctor** who opens that link (e.g. by scanning the code with
  their phone, or a doctor manually entering the code from the Doctor Dashboard)
  can see the report: patient details, prescriptions + medicines, appointment
  history, and recent fitness/food logs.
* The patient can click **Regenerate QR Code** at any time to invalidate the old
  code/link and get a fresh one - useful if it was shared with the wrong person.

## AI Assistant (Ollama, runs locally - no API key)
1. Install Ollama from https://ollama.com, then pull a model and make sure it is running:
   ```bash
   ollama pull llama3.2
   ollama serve        # skip if the Ollama app is already running; it listens on http://localhost:11434
   ```
2. Start the app as usual. The AI Assistant page shows an **Online / Offline / Model not installed** pill.
3. Optional settings (environment variables): `OLLAMA_URL` (default `http://localhost:11434`),
   `OLLAMA_MODEL` (default `llama3.2`), `OLLAMA_TIMEOUT` (default `120` seconds).
   Example: `OLLAMA_MODEL=qwen2.5:3b python app.py`. No new pip packages are needed.

**Boundaries (see `backend/ai_assistant.py`)** - the role always comes from the login session:
| | Patient | Doctor |
|---|---|---|
| Can do | general health/diet/exercise tips, explain terms, explain *their own* medicines, appointments, meals and workouts, prepare for visits | clinical reference, drug info and interactions, summarise their own appointments, draft patient instructions / SOAP notes |
| Never | diagnose, prescribe, give or change doses, interpret their results, replace a doctor | claim facts about a patient not in the data, make the final clinical decision, help with unethical requests |
| Sees | only their own profile, medicines, appointments, 7-day meal/workout summary | only their own profile and upcoming appointments (no patient records) |
| Safety net | emergency / self-harm wording gets a fixed reply (112, 108, Tele-MANAS 14416) without calling the model | answers are labelled decision support: verify doses against local guidelines |

**Summarize with AI (doctors):** the patient report page (`/report/<token>`) has a **Summarize with AI** button. The server re-reads the record from the database by QR token (the browser sends nothing), leaves out the patient's name/email/phone, computes BMI in code, and asks the model for a fixed-format summary (Overview, medicines, appointments, lifestyle, worth reviewing, data gaps) that only uses facts from the record.

Both roles: prompt-injection attempts ("ignore your instructions", "show your prompt") and off-topic requests
(code, politics, homework...) get a fixed refusal, messages are capped at 800 characters, 20 messages/minute per user,
and low temperature + a reply-length cap are used. Edit the prompts and regexes in `ai_assistant.py` to tune the behaviour.

## Notes
* Self sign-up always creates a **patient** (role is never read from the form). Doctor accounts are created in the database.
* `/database` shows table data to any logged-in user (passwords are masked). Set `ENABLE_DB_VIEWER = False` in `app.py` to turn it off.
* **Database name changed**: this project now uses its own database, `mediassist_care_db`,
  instead of the original `healthcare_db`, so importing `healthcare_db.sql` will never
  touch/overwrite any existing `healthcare_db` you already have. Change `DB_NAME` in `backend/app.py` if you ever want to point it elsewhere.
