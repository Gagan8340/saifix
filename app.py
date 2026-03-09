import os
import re
import sqlite3
import uuid
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'saifix_secret_key_2026'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

# --------------- Telegram Bot Config ---------------
TELEGRAM_BOT_TOKEN = '8744342892:AAH1QpBRvjcMGNj0NmPAeLBRkFipXdl1hn4'
TELEGRAM_CHAT_ID = '6744959005'


def send_telegram_notification(customer_name, mobile_number, appliance_type, problem_type, address, problem_description=''):
    """Send a Telegram message to the shop owner about a new repair request."""
    message = (
        f"\U0001F527 *New Repair Request*\n"
        f"\n"
        f"\U0001F464 *Customer:* {customer_name}\n"
        f"\U0001F4F1 *Mobile:* {mobile_number}\n"
        f"\U0001F3E0 *Address:* {address}\n"
        f"\U0001F4BB *Appliance:* {appliance_type}\n"
        f"\U000026A0 *Problem:* {problem_type}\n"
        f"\U0001F4DD *Description:* {problem_description or 'N/A'}\n"
        f"\n"
        f"Please follow up with the customer soon."
    )
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        response = http_requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print('[Telegram] Notification sent successfully.')
        else:
            print(f'[Telegram] Failed to send: {response.text}')
    except Exception as e:
        print(f'[Telegram] Error: {e}')


# --------------- Database Helpers ---------------

def get_db():
    """Get a database connection for the current request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close the database connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Create tables and seed initial data."""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    # --- Admins table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')

    # --- Service Requests table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS service_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            address TEXT NOT NULL,
            appliance_type TEXT NOT NULL,
            problem_type TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'Pending',
            technician_id INTEGER,
            assigned_time TIMESTAMP,
            request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_time TIMESTAMP,
            FOREIGN KEY (technician_id) REFERENCES technicians(id)
        )
    ''')

    # Migration: add columns if missing (for existing DBs)
    migrations = [
        ("ALTER TABLE service_requests ADD COLUMN status TEXT DEFAULT 'Pending'", None),
        ('ALTER TABLE service_requests ADD COLUMN completed_time TIMESTAMP', None),
        ('ALTER TABLE service_requests ADD COLUMN technician_id INTEGER', None),
        ('ALTER TABLE service_requests ADD COLUMN assigned_time TIMESTAMP', None),
        ('ALTER TABLE service_requests ADD COLUMN image_path TEXT', None),
        ('ALTER TABLE service_requests ADD COLUMN ai_suggestions TEXT', None),
        ('ALTER TABLE service_requests ADD COLUMN cancel_reason TEXT', None),
        ('ALTER TABLE service_requests ADD COLUMN cancel_description TEXT', None),
        ('ALTER TABLE service_requests ADD COLUMN admin_message TEXT', None),
    ]
    for sql, _ in migrations:
        try:
            cursor.execute(sql)
        except Exception:
            pass

    # Migrate old lowercase status values to new capitalized ones
    cursor.execute("UPDATE service_requests SET status = 'Pending' WHERE status = 'pending'")
    cursor.execute("UPDATE service_requests SET status = 'Completed' WHERE status = 'completed'")

    # --- Technicians table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS technicians (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            status TEXT DEFAULT 'Available',
            current_workload INTEGER DEFAULT 0
        )
    ''')

    # --- Spare Parts table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spare_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            part_name TEXT NOT NULL
        )
    ''')

    db.commit()

    # --- Seed Admins (only if table is empty) ---
    cursor.execute('SELECT COUNT(*) FROM admins')
    if cursor.fetchone()[0] == 0:
        admins = [
            ('Gagan', 'sanagalagagan@gmail.com', generate_password_hash('Gagan@1849')),
            ('Dwaraka Narayana', 'dwarakanarayana4579@gmail.com', generate_password_hash('Dwaraka@8340')),
        ]
        cursor.executemany('INSERT INTO admins (name, email, password) VALUES (?, ?, ?)', admins)
        db.commit()
        print('[DB] Seeded 2 admin accounts.')

    # --- Seed Spare Parts (only if table is empty) ---
    cursor.execute('SELECT COUNT(*) FROM spare_parts')
    if cursor.fetchone()[0] == 0:
        spare_parts = [
            # Fan Motors
            ('Fan Motors', 'AC Indoor Blower Motor'),
            ('Fan Motors', 'AC Outdoor Fan Motor'),
            ('Fan Motors', 'Refrigerator Condenser Fan Motor'),
            ('Fan Motors', 'Refrigerator Evaporator Fan Motor'),
            ('Fan Motors', 'Washing Machine Spin Motor'),
            ('Fan Motors', 'Washing Machine Wash Motor'),
            ('Fan Motors', 'Universal Fan Motor (Multi-speed)'),
            # Capacitors
            ('Capacitors', 'AC Compressor Run Capacitor'),
            ('Capacitors', 'AC Fan Motor Capacitor'),
            ('Capacitors', 'Refrigerator Start Capacitor'),
            ('Capacitors', 'Washing Machine Motor Capacitor'),
            ('Capacitors', 'Dual Run Capacitor'),
            ('Capacitors', 'Start Relay & Capacitor Kit'),
            # Thermostats
            ('Thermostats', 'AC Room Thermostat'),
            ('Thermostats', 'Refrigerator Thermostat'),
            ('Thermostats', 'Freezer Thermostat'),
            ('Thermostats', 'Washing Machine Water Temperature Thermostat'),
            ('Thermostats', 'Defrost Thermostat'),
            ('Thermostats', 'Adjustable Thermostat (Universal)'),
            # Sensors
            ('Sensors', 'AC Temperature Sensor (Thermistor)'),
            ('Sensors', 'AC Pipe Sensor'),
            ('Sensors', 'Refrigerator Defrost Sensor'),
            ('Sensors', 'Washing Machine Water Level Sensor'),
            ('Sensors', 'Washing Machine Door Lock Sensor'),
            ('Sensors', 'Ambient Temperature Sensor'),
            # Bimetals / Electrical Sensors
            ('Bimetals / Electrical Sensors', 'Defrost Bimetal'),
            ('Bimetals / Electrical Sensors', 'Compressor Overload Protector (OLP)'),
            ('Bimetals / Electrical Sensors', 'PTC Relay'),
            ('Bimetals / Electrical Sensors', 'Thermal Fuse'),
            ('Bimetals / Electrical Sensors', 'AC Bimetal Thermostat'),
            ('Bimetals / Electrical Sensors', 'Washing Machine Thermal Cutoff'),
            # Electrical Components
            ('Electrical Components', 'AC PCB Board (Indoor Unit)'),
            ('Electrical Components', 'AC PCB Board (Outdoor Unit)'),
            ('Electrical Components', 'Refrigerator PCB / Main Board'),
            ('Electrical Components', 'Washing Machine PCB / Control Board'),
            ('Electrical Components', 'AC Contactor / Relay'),
            ('Electrical Components', 'Power Cord / Plug Assembly'),
            ('Electrical Components', 'Voltage Stabilizer'),
            ('Electrical Components', 'Timer Switch (Washing Machine)'),
            # Valves
            ('Valves', 'AC Expansion Valve'),
            ('Valves', 'AC 4-Way Reversing Valve'),
            ('Valves', 'AC Service Valve (Charging Valve)'),
            ('Valves', 'Refrigerator Solenoid Valve'),
            ('Valves', 'Washing Machine Inlet Valve (Single)'),
            ('Valves', 'Washing Machine Inlet Valve (Double)'),
            ('Valves', 'Washing Machine Drain Valve'),
            # Capillary Tubes
            ('Capillary Tubes', 'AC Capillary Tube (0.054 inch)'),
            ('Capillary Tubes', 'AC Capillary Tube (0.064 inch)'),
            ('Capillary Tubes', 'Refrigerator Capillary Tube (0.031 inch)'),
            ('Capillary Tubes', 'Refrigerator Capillary Tube (0.036 inch)'),
            ('Capillary Tubes', 'Deep Freezer Capillary Tube'),
            ('Capillary Tubes', 'Universal Capillary Tube Roll (15m)'),
            # Refrigeration Oils
            ('Refrigeration Oils', 'Compressor Oil (Mineral Oil)'),
            ('Refrigeration Oils', 'Compressor Oil (POE — Synthetic)'),
            ('Refrigeration Oils', 'Compressor Oil for R-134a Systems'),
            ('Refrigeration Oils', 'Compressor Oil for R-410A Systems'),
            ('Refrigeration Oils', 'Flushing Oil'),
            # Charging Lines
            ('Charging Lines', 'AC Charging Hose Set (R-22)'),
            ('Charging Lines', 'AC Charging Hose Set (R-410A)'),
            ('Charging Lines', 'AC Charging Hose Set (R-32)'),
            ('Charging Lines', 'Refrigerant Charging Hose (R-134a)'),
            ('Charging Lines', 'Ball Valve Charging Adapter'),
            ('Charging Lines', 'Piercing Valve / Tap Valve'),
            # Pipes and Filters
            ('Pipes and Filters', 'Copper Pipe (1/4 inch)'),
            ('Pipes and Filters', 'Copper Pipe (3/8 inch)'),
            ('Pipes and Filters', 'Insulation Tube'),
            ('Pipes and Filters', 'AC Filter Drier'),
            ('Pipes and Filters', 'Refrigerator Filter Drier'),
            ('Pipes and Filters', 'Drain Pipe / Hose'),
            ('Pipes and Filters', 'Washing Machine Drain Hose'),
            ('Pipes and Filters', 'Washing Machine Inlet Hose'),
            # Tools and Accessories
            ('Tools and Accessories', 'Manifold Gauge Set'),
            ('Tools and Accessories', 'Flaring Tool Kit'),
            ('Tools and Accessories', 'Tube Cutter'),
            ('Tools and Accessories', 'Brazing Rod (Silver)'),
            ('Tools and Accessories', 'Brazing Rod (Copper-Phosphorus)'),
            ('Tools and Accessories', 'Vacuum Pump'),
            ('Tools and Accessories', 'Leak Detector'),
            ('Tools and Accessories', 'Fin Comb Set'),
            ('Tools and Accessories', 'AC Remote Control (Universal)'),
            # Appliance Supports
            ('Appliance Supports', 'AC Wall Mounting Bracket'),
            ('Appliance Supports', 'AC Stand / Floor Bracket'),
            ('Appliance Supports', 'Rubber Vibration Pads'),
            ('Appliance Supports', 'Washing Machine Stand (Adjustable)'),
            ('Appliance Supports', 'Refrigerator Stand'),
            ('Appliance Supports', 'AC Outdoor Unit Cover'),
            # Gas Cylinders
            ('Gas Cylinders', 'R-22 Refrigerant Gas Cylinder'),
            ('Gas Cylinders', 'R-32 Refrigerant Gas Cylinder'),
            ('Gas Cylinders', 'R-410A Refrigerant Gas Cylinder'),
            ('Gas Cylinders', 'R-134a Refrigerant Gas Cylinder'),
            ('Gas Cylinders', 'R-600a Refrigerant Gas Can'),
            ('Gas Cylinders', 'Nitrogen Gas Cylinder (for pressure testing)'),
        ]
        cursor.executemany('INSERT INTO spare_parts (category, part_name) VALUES (?, ?)', spare_parts)
        db.commit()
        print(f'[DB] Seeded {len(spare_parts)} spare parts.')

    db.close()


# Initialize database on startup
init_db()


# --------------- Routes ---------------


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/services')
def services():
    return render_template('services.html')


@app.route('/spare-parts')
def spare_parts():
    db = get_db()
    rows = db.execute('SELECT category, part_name FROM spare_parts ORDER BY category, part_name').fetchall()
    # Build ordered category list and parts dict
    categories = []
    parts_by_category = {}
    for row in rows:
        cat = row['category']
        if cat not in parts_by_category:
            categories.append(cat)
            parts_by_category[cat] = []
        parts_by_category[cat].append(row['part_name'])
    return render_template('spare_parts.html', categories=categories, parts_by_category=parts_by_category)


@app.route('/location')
def location():
    return render_template('location.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/request-repair', methods=['GET', 'POST'])
def request_repair():
    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        mobile_raw = request.form.get('mobile_number', '').strip()
        confirm_raw = request.form.get('confirm_mobile', '').strip()
        address = request.form.get('address', '').strip()
        appliance_type = request.form.get('appliance_type', '').strip()
        problem_type = request.form.get('problem_type', '').strip()
        problem_description = request.form.get('problem_description', '').strip()

        # Enforce 2000 character limit on problem description
        if len(problem_description) > 2000:
            problem_description = problem_description[:2000]

        # Strip any spaces, dashes, or +91 prefix the user may have typed
        digits = re.sub(r'[^0-9]', '', mobile_raw)
        confirm_digits = re.sub(r'[^0-9]', '', confirm_raw)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        if digits.startswith('0'):
            digits = digits[1:]

        # Validate: exactly 10 digits, starts with 6-9
        if not re.match(r'^[6-9]\d{9}$', digits):
            flash('Please enter a valid 10-digit Indian mobile number.', 'error')
            return render_template('request_repair.html')

        # Validate: confirm number matches
        if digits != confirm_digits:
            flash('Mobile numbers do not match. Please check again.', 'error')
            return render_template('request_repair.html')

        mobile_number = '+91' + digits

        if not all([customer_name, address, appliance_type, problem_type]):
            flash('Please fill in all required fields.', 'error')
            return render_template('request_repair.html')

        # Check 24-hour rate limit for this mobile number
        db = get_db()
        cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        existing = db.execute(
            'SELECT id FROM service_requests WHERE mobile_number = ? AND request_time >= ?',
            (mobile_number, cutoff)
        ).fetchone()

        if existing:
            flash('A repair request has already been submitted from this number. Please wait 24 hours before submitting another request.', 'error')
            return render_template('request_repair.html')

        # Handle image upload
        image_path = None
        file = request.files.get('image')
        if file and file.filename:
            if not allowed_file(file.filename):
                flash('Only JPG, JPEG, and PNG image files are allowed.', 'error')
                return render_template('request_repair.html')
            file.seek(0, 2)
            size = file.tell()
            file.seek(0)
            if size > 5 * 1024 * 1024:
                flash('File size must be 5 MB or less.', 'error')
                return render_template('request_repair.html')
            ext = file.filename.rsplit('.', 1)[1].lower()
            safe_name = uuid.uuid4().hex + '.' + ext
            file.save(os.path.join(UPLOAD_FOLDER, safe_name))
            image_path = 'uploads/' + safe_name

        db.execute(
            '''INSERT INTO service_requests
               (customer_name, mobile_number, address, appliance_type, problem_type, description, image_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (customer_name, mobile_number, address, appliance_type, problem_type, problem_description, image_path)
        )
        db.commit()

        # Send Telegram notification to shop owner
        send_telegram_notification(customer_name, mobile_number, appliance_type, problem_type, address, problem_description)

        flash('Your repair request has been submitted successfully. Our team will contact you within 24 hours.', 'success')
        return redirect(url_for('request_repair'))

    return render_template('request_repair.html')


@app.route('/api/check-duplicate', methods=['POST'])
def api_check_duplicate():
    """Check if a repair request exists for the given mobile number within 24 hours."""
    import json as _json
    mobile_raw = request.form.get('mobile', '').strip()
    digits = re.sub(r'[^0-9]', '', mobile_raw)
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if digits.startswith('0'):
        digits = digits[1:]
    if not re.match(r'^[6-9]\d{9}$', digits):
        return app.response_class(
            response=_json.dumps({'exists': False}),
            status=200, mimetype='application/json'
        )
    mobile_number = '+91' + digits
    db = get_db()
    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    existing = db.execute(
        'SELECT id FROM service_requests WHERE mobile_number = ? AND request_time >= ?',
        (mobile_number, cutoff)
    ).fetchone()
    return app.response_class(
        response=_json.dumps({'exists': bool(existing)}),
        status=200, mimetype='application/json'
    )


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        admin = db.execute('SELECT * FROM admins WHERE email = ?', (email,)).fetchone()

        if admin and check_password_hash(admin['password'], password):
            session.permanent = True
            session['admin_logged_in'] = True
            session['admin_name'] = admin['name']
            session['admin_email'] = admin['email']
            flash('Login successful!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid email or password.', 'error')
    return render_template('admin_login.html')


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        flash('Please login first.', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    # Active requests = everything not Completed and not Cancelled
    active_requests = db.execute(
        """SELECT sr.*, t.name AS technician_name, t.phone_number AS technician_phone
           FROM service_requests sr
           LEFT JOIN technicians t ON sr.technician_id = t.id
           WHERE sr.status NOT IN ('Completed', 'Cancelled')
           ORDER BY sr.id DESC"""
    ).fetchall()
    completed_requests = db.execute(
        """SELECT sr.*, t.name AS technician_name, t.phone_number AS technician_phone
           FROM service_requests sr
           LEFT JOIN technicians t ON sr.technician_id = t.id
           WHERE sr.status = 'Completed'
           ORDER BY sr.completed_time DESC"""
    ).fetchall()
    cancelled_requests = db.execute(
        """SELECT sr.*, t.name AS technician_name, t.phone_number AS technician_phone
           FROM service_requests sr
           LEFT JOIN technicians t ON sr.technician_id = t.id
           WHERE sr.status = 'Cancelled'
           ORDER BY sr.id DESC"""
    ).fetchall()
    technicians = db.execute('SELECT * FROM technicians ORDER BY name').fetchall()
    spare_parts = db.execute('SELECT * FROM spare_parts ORDER BY category, part_name').fetchall()
    return render_template(
        'admin_dashboard.html',
        active_requests=active_requests,
        completed_requests=completed_requests,
        cancelled_requests=cancelled_requests,
        technicians=technicians,
        spare_parts=spare_parts
    )


@app.route('/admin/spare-parts/add', methods=['POST'])
def add_spare_part():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    category = request.form.get('category', '').strip()
    part_name = request.form.get('part_name', '').strip()

    if category and part_name:
        db = get_db()
        db.execute('INSERT INTO spare_parts (category, part_name) VALUES (?, ?)', (category, part_name))
        db.commit()
        flash('Spare part added successfully!', 'success')
    else:
        flash('Both category and part name are required.', 'error')

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/spare-parts/delete/<int:id>', methods=['POST'])
def delete_spare_part(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    db = get_db()
    db.execute('DELETE FROM spare_parts WHERE id = ?', (id,))
    db.commit()
    flash('Spare part deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/complete/<int:id>', methods=['POST'])
def complete_request(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    db = get_db()
    # Decrease technician workload if one was assigned
    req = db.execute('SELECT technician_id FROM service_requests WHERE id = ?', (id,)).fetchone()
    if req and req['technician_id']:
        db.execute(
            'UPDATE technicians SET current_workload = MAX(current_workload - 1, 0) WHERE id = ?',
            (req['technician_id'],)
        )
    db.execute(
        "UPDATE service_requests SET status = 'Completed', completed_time = CURRENT_TIMESTAMP WHERE id = ?",
        (id,)
    )
    db.commit()
    flash('Request marked as completed!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/cancel/<int:id>', methods=['POST'])
def cancel_request(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    cancel_description = request.form.get('cancel_description', '').strip()

    if not cancel_reason:
        flash('Please select a cancellation reason.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    req = db.execute('SELECT technician_id FROM service_requests WHERE id = ?', (id,)).fetchone()
    if req and req['technician_id']:
        db.execute(
            'UPDATE technicians SET current_workload = MAX(current_workload - 1, 0) WHERE id = ?',
            (req['technician_id'],)
        )
    db.execute(
        """UPDATE service_requests
           SET status = 'Cancelled', cancel_reason = ?, cancel_description = ?
           WHERE id = ?""",
        (cancel_reason, cancel_description, id)
    )
    db.commit()
    flash(f'Request cancelled — {cancel_reason}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/message/<int:id>', methods=['POST'])
def send_admin_message(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    message = request.form.get('admin_message', '').strip()
    if not message:
        flash('Message cannot be empty.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    db.execute('UPDATE service_requests SET admin_message = ? WHERE id = ?', (message, id))
    db.commit()
    flash('Advice message sent to customer!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/update-status/<int:id>', methods=['POST'])
def update_request_status(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    new_status = request.form.get('status', '').strip()
    allowed = ['Pending', 'Technician Assigned', 'In Progress', 'Completed', 'Cancelled']
    if new_status not in allowed:
        flash('Invalid status.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    if new_status == 'Completed':
        db.execute(
            "UPDATE service_requests SET status = 'Completed', completed_time = CURRENT_TIMESTAMP WHERE id = ?",
            (id,)
        )
    else:
        db.execute(
            'UPDATE service_requests SET status = ? WHERE id = ?',
            (new_status, id)
        )
    db.commit()
    flash(f'Status updated to "{new_status}".', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/assign/<int:id>', methods=['POST'])
def assign_technician(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    technician_id = request.form.get('technician_id', '').strip()
    if not technician_id:
        flash('Please select a technician.', 'error')
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    # Remove workload from previously assigned technician if any
    old_req = db.execute('SELECT technician_id FROM service_requests WHERE id = ?', (id,)).fetchone()
    if old_req and old_req['technician_id']:
        db.execute(
            'UPDATE technicians SET current_workload = MAX(current_workload - 1, 0) WHERE id = ?',
            (old_req['technician_id'],)
        )

    db.execute(
        "UPDATE service_requests SET technician_id = ?, assigned_time = CURRENT_TIMESTAMP, status = 'Technician Assigned' WHERE id = ?",
        (technician_id, id)
    )
    db.execute(
        'UPDATE technicians SET current_workload = current_workload + 1 WHERE id = ?',
        (technician_id,)
    )
    db.commit()
    tech = db.execute('SELECT name FROM technicians WHERE id = ?', (technician_id,)).fetchone()
    flash(f'Technician "{tech["name"]}" assigned successfully!', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/requests/delete/<int:id>', methods=['POST'])
def delete_request(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    db = get_db()
    db.execute('DELETE FROM service_requests WHERE id = ?', (id,))
    db.commit()
    flash('Repair request deleted.', 'success')
    return redirect(url_for('admin_dashboard'))


# --------------- Technician Management Routes ---------------

@app.route('/admin/technicians')
def manage_technicians():
    if not session.get('admin_logged_in'):
        flash('Please login first.', 'error')
        return redirect(url_for('admin_login'))

    db = get_db()
    technicians = db.execute('SELECT * FROM technicians ORDER BY name').fetchall()
    return render_template('admin_technicians.html', technicians=technicians)


@app.route('/admin/technicians/add', methods=['POST'])
def add_technician():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    name = request.form.get('name', '').strip()
    phone_number = request.form.get('phone_number', '').strip()

    if not name or not phone_number:
        flash('Technician name and phone number are required.', 'error')
        return redirect(url_for('manage_technicians'))

    db = get_db()
    db.execute('INSERT INTO technicians (name, phone_number) VALUES (?, ?)', (name, phone_number))
    db.commit()
    flash(f'Technician "{name}" added successfully!', 'success')
    return redirect(url_for('manage_technicians'))


@app.route('/admin/technicians/edit/<int:id>', methods=['POST'])
def edit_technician(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    name = request.form.get('name', '').strip()
    phone_number = request.form.get('phone_number', '').strip()
    status = request.form.get('status', '').strip()

    allowed_statuses = ['Available', 'Busy', 'On Leave']
    if status not in allowed_statuses:
        flash('Invalid technician status.', 'error')
        return redirect(url_for('manage_technicians'))

    if not name or not phone_number:
        flash('Technician name and phone number are required.', 'error')
        return redirect(url_for('manage_technicians'))

    db = get_db()
    db.execute(
        'UPDATE technicians SET name = ?, phone_number = ?, status = ? WHERE id = ?',
        (name, phone_number, status, id)
    )
    db.commit()
    flash(f'Technician "{name}" updated.', 'success')
    return redirect(url_for('manage_technicians'))


@app.route('/admin/technicians/delete/<int:id>', methods=['POST'])
def delete_technician(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    db = get_db()
    # Unassign from any requests
    db.execute('UPDATE service_requests SET technician_id = NULL WHERE technician_id = ?', (id,))
    db.execute('DELETE FROM technicians WHERE id = ?', (id,))
    db.commit()
    flash('Technician deleted.', 'success')
    return redirect(url_for('manage_technicians'))


# --------------- Customer Status Check ---------------

@app.route('/check-status', methods=['GET', 'POST'])
def check_status():
    results = None
    mobile_display = ''
    if request.method == 'POST':
        mobile_raw = request.form.get('mobile_number', '').strip()
        digits = re.sub(r'[^0-9]', '', mobile_raw)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        if digits.startswith('0'):
            digits = digits[1:]

        if not re.match(r'^[6-9]\d{9}$', digits):
            flash('Please enter a valid 10-digit Indian mobile number.', 'error')
            return render_template('check_status.html', results=None, mobile_display='')

        mobile_number = '+91' + digits
        mobile_display = digits
        db = get_db()
        results = db.execute(
            """SELECT sr.*, t.name AS technician_name, t.phone_number AS technician_phone
               FROM service_requests sr
               LEFT JOIN technicians t ON sr.technician_id = t.id
               WHERE sr.mobile_number = ?
               ORDER BY sr.id DESC""",
            (mobile_number,)
        ).fetchall()

        if not results:
            flash('No repair requests found for this mobile number.', 'error')

    return render_template('check_status.html', results=results, mobile_display=mobile_display)


# --------------- Analytics API ---------------

@app.route('/admin/analytics-data')
def analytics_data():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401

    db = get_db()

    # Total requests
    total = db.execute('SELECT COUNT(*) AS cnt FROM service_requests').fetchone()['cnt']

    # Completed jobs
    completed = db.execute("SELECT COUNT(*) AS cnt FROM service_requests WHERE status = 'Completed'").fetchone()['cnt']

    # Most repaired appliance type
    appliance_stats = db.execute(
        'SELECT appliance_type, COUNT(*) AS cnt FROM service_requests GROUP BY appliance_type ORDER BY cnt DESC'
    ).fetchall()
    appliance_labels = [r['appliance_type'] for r in appliance_stats]
    appliance_counts = [r['cnt'] for r in appliance_stats]

    # Monthly service requests (last 12 months)
    monthly = db.execute(
        """SELECT strftime('%Y-%m', request_time) AS month, COUNT(*) AS cnt
           FROM service_requests
           WHERE request_time >= date('now', '-12 months')
           GROUP BY month ORDER BY month"""
    ).fetchall()
    month_labels = [r['month'] for r in monthly]
    month_counts = [r['cnt'] for r in monthly]

    # Technician workload distribution
    tech_workload = db.execute(
        'SELECT name, current_workload FROM technicians ORDER BY name'
    ).fetchall()
    tech_labels = [r['name'] for r in tech_workload]
    tech_counts = [r['current_workload'] for r in tech_workload]

    # Status distribution
    status_dist = db.execute(
        'SELECT status, COUNT(*) AS cnt FROM service_requests GROUP BY status'
    ).fetchall()
    status_labels = [r['status'] for r in status_dist]
    status_counts = [r['cnt'] for r in status_dist]

    return jsonify({
        'total_requests': total,
        'completed_jobs': completed,
        'appliance_labels': appliance_labels,
        'appliance_counts': appliance_counts,
        'month_labels': month_labels,
        'month_counts': month_counts,
        'tech_labels': tech_labels,
        'tech_counts': tech_counts,
        'status_labels': status_labels,
        'status_counts': status_counts,
    })


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('admin_login'))


if __name__ == '__main__':
    app.run(debug=True)
