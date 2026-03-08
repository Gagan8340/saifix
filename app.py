import os
import re
import sqlite3
import requests as http_requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'saifix_secret_key_2026'

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database.db')

# --------------- Telegram Bot Config ---------------
TELEGRAM_BOT_TOKEN = '8744342892:AAH1QpBRvjcMGNj0NmPAeLBRkFipXdl1hn4'
TELEGRAM_CHAT_ID = '6744959005'


def send_telegram_notification(customer_name, mobile_number, appliance_type, problem_type, address):
    """Send a Telegram message to the shop owner about a new repair request."""
    message = (
        f"\U0001F527 *New Repair Request*\n"
        f"\n"
        f"\U0001F464 *Customer:* {customer_name}\n"
        f"\U0001F4F1 *Mobile:* {mobile_number}\n"
        f"\U0001F3E0 *Address:* {address}\n"
        f"\U0001F4BB *Appliance:* {appliance_type}\n"
        f"\U000026A0 *Problem:* {problem_type}\n"
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
            status TEXT DEFAULT 'pending',
            request_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_time TIMESTAMP
        )
    ''')

    # Migration: add status & completed_time columns if missing (for existing DBs)
    try:
        cursor.execute("ALTER TABLE service_requests ADD COLUMN status TEXT DEFAULT 'pending'")
    except Exception:
        pass
    try:
        cursor.execute('ALTER TABLE service_requests ADD COLUMN completed_time TIMESTAMP')
    except Exception:
        pass

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
        address = request.form.get('address', '').strip()
        appliance_type = request.form.get('appliance_type', '').strip()
        problem_type = request.form.get('problem_type', '').strip()
        description = request.form.get('description', '').strip()

        # Strip any spaces, dashes, or +91 prefix the user may have typed
        digits = re.sub(r'[^0-9]', '', mobile_raw)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        if digits.startswith('0'):
            digits = digits[1:]

        # Validate: exactly 10 digits, starts with 6-9
        if not re.match(r'^[6-9]\d{9}$', digits):
            flash('Please enter a valid 10-digit Indian mobile number.', 'error')
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

        db.execute(
            '''INSERT INTO service_requests
               (customer_name, mobile_number, address, appliance_type, problem_type, description)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (customer_name, mobile_number, address, appliance_type, problem_type, description)
        )
        db.commit()

        # Send Telegram notification to shop owner
        send_telegram_notification(customer_name, mobile_number, appliance_type, problem_type, address)

        flash('Your repair request has been submitted successfully. Our team will contact you within 24 hours.', 'success')
        return redirect(url_for('request_repair'))

    return render_template('request_repair.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        db = get_db()
        admin = db.execute('SELECT * FROM admins WHERE email = ?', (email,)).fetchone()

        if admin and check_password_hash(admin['password'], password):
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
    pending_requests = db.execute(
        "SELECT * FROM service_requests WHERE status IS NULL OR status = 'pending' ORDER BY id DESC"
    ).fetchall()
    completed_requests = db.execute(
        "SELECT * FROM service_requests WHERE status = 'completed' ORDER BY completed_time DESC"
    ).fetchall()
    spare_parts = db.execute('SELECT * FROM spare_parts ORDER BY category, part_name').fetchall()
    return render_template(
        'admin_dashboard.html',
        pending_requests=pending_requests,
        completed_requests=completed_requests,
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
    db.execute(
        "UPDATE service_requests SET status = 'completed', completed_time = CURRENT_TIMESTAMP WHERE id = ?",
        (id,)
    )
    db.commit()
    flash('Request marked as completed!', 'success')
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


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_name', None)
    session.pop('admin_email', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('admin_login'))


if __name__ == '__main__':
    app.run(debug=True)
