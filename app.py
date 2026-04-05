from datetime import datetime

from flask import Flask, redirect, render_template, request, url_for
import requests
import threading
import time

app = Flask(__name__)

# ---------------------------
# DATA
# ---------------------------
slots = [{
    "date": "10-04-2026",
    "morning": "available",
    "evening": "available"
}]

# Patients: id, name, phone, age (optional), date_of_birth (YYYY-MM-DD optional)
patients = [
    {"id": 1, "name": "Test Patient", "phone": "9999999999", "age": "", "date_of_birth": ""},
    {"id": 2, "name": "Other Patient", "phone": "8888888888", "age": "", "date_of_birth": ""},
]

# Appointments: patient_id, date (DD-MM-YYYY), slot, status ("active"|"completed"), follow_up (YYYY-MM-DD or "")
appointments = [
    {
        "patient_id": 1,
        "date": "10-04-2026",
        "slot": "morning",
        "status": "active",
        "follow_up": "",
    },
    {
        "patient_id": 2,
        "date": "10-04-2026",
        "slot": "evening",
        "status": "active",
        "follow_up": "",
    },
]

user_state = {}
user_lang = {}

# ---------------------------
# STAFF LOGIN
# ---------------------------
doctor_credentials = {
    "username": "doctor",
    "password": "123",
}
reception_credentials = {
    "username": "reception",
    "password": "123",
}

# ---------------------------
# TELEGRAM CONFIG
# ---------------------------
TOKEN = "8232333068:AAF_OP9xa3z90DiVs7BROtp7DZiDk2KU4WM"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)


def _greeting_for_now():
    h = datetime.now().hour
    if h < 12:
        return "Good morning"
    if h < 17:
        return "Good afternoon"
    return "Good evening"


def _patient_by_id(patient_id):
    for p in patients:
        if p.get("id") == patient_id:
            return p
    return None


def _normalize_patient_phone(phone):
    return (phone or "").strip()


def _parse_age(age_raw):
    if age_raw is None or age_raw == "":
        return ""
    try:
        return int(str(age_raw).strip())
    except (TypeError, ValueError):
        return ""


def add_patient(name, phone, age=None, date_of_birth=None):
    """
    Append a new patient with id = len(patients) + 1, or return the existing
    record if the same phone is already registered (repeat visit / same person).
    """
    name = (name or "").strip()
    phone_n = _normalize_patient_phone(phone)
    for p in patients:
        if _normalize_patient_phone(p.get("phone")) == phone_n:
            return p
    patient_id = len(patients) + 1
    dob = (date_of_birth or "").strip()
    record = {
        "id": patient_id,
        "name": name,
        "phone": phone_n,
        "age": _parse_age(age),
        "date_of_birth": dob,
    }
    patients.append(record)
    return record


def _iso_date_to_dd_mm_yyyy(iso_date):
    if not iso_date:
        return ""
    try:
        return datetime.strptime(iso_date.strip(), "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso_date.strip()


def create_appointment_for_patient(patient_id, date_dd_mm_yyyy, slot, status="active", follow_up=""):
    """Attach an appointment to an existing patient. date_dd_mm_yyyy must match slot row format."""
    if slot not in ("morning", "evening"):
        raise ValueError("slot must be 'morning' or 'evening'")
    try:
        pid = int(patient_id)
    except (TypeError, ValueError):
        return None, "invalid_patient"
    if not _patient_by_id(pid):
        return None, "invalid_patient"
    if _appointment_for(date_dd_mm_yyyy, slot):
        return None, "slot_taken"
    appt = {
        "patient_id": pid,
        "date": date_dd_mm_yyyy,
        "slot": slot,
        "status": status,
        "follow_up": (follow_up or "").strip(),
    }
    appointments.append(appt)
    return appt, None


def create_appointment(name, phone, date_str, slot, status="active", follow_up=""):
    """
    Resolve patient via add_patient (unique id per person, stable id for same phone),
    then append an appointment with that patient_id.
    """
    if slot not in ("morning", "evening"):
        raise ValueError("slot must be 'morning' or 'evening'")
    patient = add_patient(name, phone)
    appt = {
        "patient_id": patient["id"],
        "date": date_str,
        "slot": slot,
        "status": status,
        "follow_up": (follow_up or "").strip(),
    }
    appointments.append(appt)
    return appt


def _appointment_for(date_str, period):
    for a in appointments:
        if a.get("date") == date_str and a.get("slot") == period:
            return a
    return None


def _appt_active(appt):
    """Only appointments with status 'active' appear on the dashboard as bookings."""
    if not appt:
        return False
    return appt.get("status", "active") == "active"


def _appt_follow_up_iso(appt):
    if not appt:
        return ""
    v = appt.get("follow_up", appt.get("follow_up_date", ""))
    return (v or "").strip()


def _half_slot_card(slot_row, period):
    """Build dashboard card fields for one half-day (morning or evening)."""
    half = "morning" if period == "morning" else "evening"
    slot_status = slot_row.get(half)
    date_key = slot_row.get("date", "")
    appt = _appointment_for(date_key, period)
    fu = _appt_follow_up_iso(appt) if appt else ""

    if slot_status == "available":
        return {
            "line_class": "available",
            "line_text": "Available",
            "attend": False,
            "followup_form": False,
            "follow_up_value": "",
        }

    if appt and _appt_active(appt):
        patient = _patient_by_id(appt.get("patient_id"))
        if patient:
            line = f"Patient: {patient['name']} (ID: {patient['id']})"
        else:
            line = "Booked (no patient on file)"
        return {
            "line_class": "booked",
            "line_text": line,
            "attend": bool(patient),
            "followup_form": True,
            "follow_up_value": fu,
        }

    if appt and not _appt_active(appt):
        line = "Attended"
        if fu:
            line = f"{line} — Follow-up: {fu}"
        return {
            "line_class": "completed",
            "line_text": line,
            "attend": False,
            "followup_form": True,
            "follow_up_value": fu,
        }

    return {
        "line_class": "booked",
        "line_text": "Booked (no patient on file)",
        "attend": False,
        "followup_form": False,
        "follow_up_value": "",
    }


# ---------------------------
# TELEGRAM BOT
# ---------------------------
def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 25}
    if offset:
        params["offset"] = offset
    # (connect timeout, read timeout) — read must exceed long-poll timeout
    r = requests.get(url, params=params, timeout=(15, 40))
    return r.json()


def run_bot():
    print("Bot Running 🚀")
    last_update_id = None

    while True:
        try:
            updates = get_updates(last_update_id)
            if not isinstance(updates, dict):
                time.sleep(2)
                continue
            if updates.get("ok") is False:
                print("Telegram API:", updates.get("description", updates))
                time.sleep(3)
                continue

            for update in updates.get("result", []):
                update_id = update["update_id"]
                last_update_id = update_id + 1

                if "message" in update:
                    chat_id = update["message"]["chat"]["id"]
                    text = update["message"].get("text", "").strip()

                    state = user_state.get(chat_id, "start")
                    lang = user_lang.get(chat_id, None)

                    if text == "/start":
                        user_state[chat_id] = "language"
                        user_lang[chat_id] = None

                        reply = "Pathak Clinic Appointment\n\n1. English\n2. हिंदी"

                    elif state == "language":
                        if text == "1":
                            user_lang[chat_id] = "en"
                            user_state[chat_id] = "availability"
                            reply = "Are you available?\n1. Yes\n2. Later\n3. Not needed"

                        elif text == "2":
                            user_lang[chat_id] = "hi"
                            user_state[chat_id] = "availability"
                            reply = "क्या आप उपलब्ध हैं?\n1. हाँ\n2. बाद में\n3. नहीं"

                        else:
                            reply = "Select 1 or 2"

                    elif state == "availability":
                        if text == "1":
                            user_state[chat_id] = "slot"
                            reply = "Choose slot:\n1. Morning\n2. Evening"

                        elif text == "2":
                            reply = "We will remind you 👍"

                        elif text == "3":
                            reply = "Alright 👍"

                        else:
                            reply = "Invalid input"

                    elif state == "slot":
                        slot = slots[0]

                        if text == "1":
                            if slot["morning"] == "available":
                                slot["morning"] = "booked"
                                reply = "Morning booked ✅"
                            else:
                                reply = "Already booked ❌"

                        elif text == "2":
                            if slot["evening"] == "available":
                                slot["evening"] = "booked"
                                reply = "Evening booked ✅"
                            else:
                                reply = "Already booked ❌"

                        else:
                            reply = "Invalid"

                    else:
                        reply = "Type /start"

                    try:
                        send_message(chat_id, reply)
                    except requests.RequestException as e:
                        print(f"send_message failed: {e}")

            time.sleep(0.5)

        except requests.RequestException as e:
            print(f"Bot poll error (retrying): {e}")
            time.sleep(3)
        except Exception as e:
            print(f"Bot error (retrying): {e}")
            time.sleep(3)

# ---------------------------
# LOGIN ROUTE
# ---------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if (username == doctor_credentials["username"] and
                password == doctor_credentials["password"]):
            return redirect(url_for('doctor_dashboard'))

        if (username == reception_credentials["username"] and
                password == reception_credentials["password"]):
            return redirect(url_for('reception_dashboard'))

        return render_template(
            'doctor_login.html',
            error='Invalid username or password.',
        )

    return render_template('doctor_login.html')


def _reception_appointment_rows():
    rows = []
    for a in appointments:
        p = _patient_by_id(a.get("patient_id"))
        rows.append({
            "date": a.get("date", ""),
            "slot": a.get("slot", ""),
            "status": a.get("status", "active"),
            "patient_id": a.get("patient_id"),
            "patient_name": p["name"] if p else "—",
        })
    return rows


@app.route('/reception')
def reception_dashboard():
    return render_template(
        'reception_dashboard.html',
        patients=patients,
        appointment_rows=_reception_appointment_rows(),
        notice=request.args.get('notice', ''),
        error=request.args.get('error', ''),
    )


@app.route('/reception/add-patient', methods=['POST'])
def reception_add_patient():
    name = request.form.get('name', '')
    phone = request.form.get('phone', '')
    age = request.form.get('age', '')
    dob = request.form.get('date_of_birth', '')
    n = len(patients)
    add_patient(name, phone, age=age, date_of_birth=dob)
    if len(patients) == n:
        return redirect(url_for('reception_dashboard', notice='patient_exists'))
    return redirect(url_for('reception_dashboard', notice='patient_added'))


@app.route('/reception/add-appointment', methods=['POST'])
def reception_add_appointment():
    pid = request.form.get('patient_id', '')
    iso = request.form.get('appt_date', '').strip()
    slot = request.form.get('slot', '').strip()
    if slot not in ('morning', 'evening'):
        return redirect(url_for('reception_dashboard', error='bad_slot'))
    dd = _iso_date_to_dd_mm_yyyy(iso)
    if not dd:
        return redirect(url_for('reception_dashboard', error='bad_date'))
    _, err = create_appointment_for_patient(pid, dd, slot)
    if err == 'invalid_patient':
        return redirect(url_for('reception_dashboard', error='bad_patient'))
    if err == 'slot_taken':
        return redirect(url_for('reception_dashboard', error='slot_taken'))
    return redirect(url_for('reception_dashboard', notice='appointment_added'))

# ---------------------------
# DOCTOR DASHBOARD (BASIC UI)
# ---------------------------
@app.route('/doctor')
def doctor_dashboard():
    dashboard_slots = []
    for s in slots:
        raw = s.get("date", "")
        disp = raw
        if raw:
            try:
                disp = datetime.strptime(raw, "%d-%m-%Y").strftime("%B %d, %Y")
            except ValueError:
                pass
        dashboard_slots.append({
            "display_date": disp,
            "date_key": s.get("date", ""),
            "morning": _half_slot_card(s, "morning"),
            "evening": _half_slot_card(s, "evening"),
        })
    return render_template(
        'doctor_dashboard.html',
        active_nav='dashboard',
        greeting=_greeting_for_now(),
        today_display=datetime.now().strftime('%A, %B %d, %Y'),
        slots=dashboard_slots,
    )


@app.route('/doctor/attend', methods=['POST'])
def doctor_attend():
    date_str = request.form.get('date', '').strip()
    period = request.form.get('slot', '').strip()
    if period not in ('morning', 'evening'):
        return redirect(url_for('doctor_dashboard'))
    appt = _appointment_for(date_str, period)
    if not appt or appt.get("status", "active") != "active":
        return redirect(url_for('doctor_dashboard'))
    appt["status"] = "completed"
    return redirect(url_for('doctor_dashboard'))


@app.route('/doctor/follow-up', methods=['POST'])
def doctor_follow_up():
    date_str = request.form.get('date', '').strip()
    period = request.form.get('slot', '').strip()
    raw = request.form.get('follow_up', '').strip()
    if period not in ('morning', 'evening'):
        return redirect(url_for('doctor_dashboard'))
    appt = _appointment_for(date_str, period)
    if not appt:
        return redirect(url_for('doctor_dashboard'))
    appt['follow_up'] = raw
    return redirect(url_for('doctor_dashboard'))


@app.route('/doctor/patients')
def doctor_patients():
    return render_template(
        'doctor_patients.html',
        active_nav='patients',
        patients=patients,
    )


@app.route('/doctor/analytics')
def doctor_analytics():
    return render_template('doctor_analytics.html', active_nav='analytics')

# ---------------------------
# RUN
# ---------------------------
if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(debug=False, use_reloader=False)