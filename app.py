from flask import session, g
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timedelta
import csv
from io import StringIO
from flask import Response
import json
from datetime import date
KITTY_START_DATE = date(2026, 8, 2)  # Sunday, 2nd August 2026

app = Flask(__name__)
# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        if not session.get('is_admin'):
            flash('You do not have permission to access that page.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
app.secret_key = os.environ.get('SECRET_KEY', 'praise-team-kitty-2024')

def get_db():
    conn = psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require')
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            username TEXT UNIQUE,
            password_hash TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            join_date DATE DEFAULT CURRENT_DATE,
            status TEXT DEFAULT 'active'
        )
    ''')

    # In case table exists from earlier, add columns if missing
    cur.execute("ALTER TABLE members ADD COLUMN IF NOT EXISTS username TEXT UNIQUE")
    cur.execute("ALTER TABLE members ADD COLUMN IF NOT EXISTS password_hash TEXT")
    cur.execute("ALTER TABLE members ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
    cur.execute("ALTER TABLE members ADD COLUMN IF NOT EXISTS credit REAL DEFAULT 0.0")    

    # Create contributions and expenses tables (unchanged)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS contributions (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
            amount REAL NOT NULL DEFAULT 50.0,
            week_start DATE NOT NULL,
            date_paid TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            expense_date DATE NOT NULL,
            recorded_by TEXT,
            date_recorded TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create default admin user if not exists
    cur.execute("SELECT id FROM members WHERE username = 'admin'")
    if not cur.fetchone():
        cur.execute('''
            INSERT INTO members (name, username, password_hash, is_admin)
            VALUES ('Admin', 'admin', %s, TRUE)
        ''', (generate_password_hash('admin123'),))

    conn.commit()
    cur.close()
    conn.close()

def get_total_contributions():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM contributions")
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['total']

def get_total_expenses():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COALESCE(SUM(amount), 0) as total FROM expenses")
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['total']

def get_active_members_count():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as count FROM members WHERE status='active'")
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['count']

def get_current_week_start():
    today = datetime.now()
    return (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
def get_expected_weeks():
    """Number of Sundays from KITTY_START_DATE to current week, inclusive."""
    current_week = datetime.strptime(get_current_week_start(), '%Y-%m-%d').date()
    start = KITTY_START_DATE
    if current_week < start:
        return 0
    days_diff = (current_week - start).days
    return days_diff // 7 + 1

def get_expected_total():
    """Expected total contribution per member."""
    return get_expected_weeks() * 50.0
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM members WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            flash('Logged in successfully!', 'success')
            if user['is_admin']:
                return redirect(url_for('index'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM members WHERE id = %s", (user_id,))
    member = cur.fetchone()
    
    cur.execute('''
        SELECT id, amount, week_start, date_paid
        FROM contributions
        WHERE member_id = %s
        ORDER BY week_start DESC
    ''', (user_id,))
    contributions = cur.fetchall()
    
    cur.execute("SELECT COALESCE(SUM(amount), 0) as total_paid FROM contributions WHERE member_id = %s", (user_id,))
    total_paid = cur.fetchone()['total_paid']
    
    cur.execute("SELECT COUNT(*) as weeks_paid FROM contributions WHERE member_id = %s", (user_id,))
    weeks_paid = cur.fetchone()['weeks_paid']

    cur.execute("SELECT COALESCE(credit, 0) as credit FROM members WHERE id = %s", (user_id,))
    credit = cur.fetchone()['credit']
    expected_total = get_expected_total()
    balance = total_paid + credit - expected_total
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html', member=member, contributions=contributions, total_paid=total_paid, weeks_paid=weeks_paid, credit=credit, balance=balance)
@app.route('/')
@admin_required
def index():
    total_contributions = get_total_contributions()
    total_expenses = get_total_expenses()
    balance = total_contributions - total_expenses
    active_members = get_active_members_count()

    # Weekly progress
    current_week = get_current_week_start()
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as paid_count FROM contributions WHERE week_start = %s", (current_week,))
    paid_this_week = cur.fetchone()['paid_count']
    if active_members > 0:
        progress_percent = int((paid_this_week / active_members) * 100)
    else:
        progress_percent = 0

    # Recent transactions
    cur.execute('''
        SELECT m.name, c.amount, c.date_paid
        FROM contributions c
        JOIN members m ON c.member_id = m.id
        ORDER BY c.date_paid DESC LIMIT 5
    ''')
    recent_contributions = cur.fetchall()

    cur.execute('''
        SELECT description, amount, expense_date
        FROM expenses
        ORDER BY expense_date DESC LIMIT 5
    ''')
    recent_expenses = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('index.html',
                         total_contributions=total_contributions,
                         total_expenses=total_expenses,
                         balance=balance,
                         active_members=active_members,
                         paid_this_week=paid_this_week,
                         progress_percent=progress_percent,
                         recent_contributions=recent_contributions,
                         recent_expenses=recent_expenses)
@app.route('/members')
@admin_required
def members():
    search_query = request.args.get('search', '').strip()
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if search_query:
              cur.execute('''
            SELECT m.*,
                   (SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) as total_paid,
                   (SELECT COUNT(*) FROM contributions c WHERE c.member_id = m.id) as weeks_paid,
                   %s as expected_total,
                   ((SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) + COALESCE(m.credit, 0) - %s) as balance,
                   COALESCE(m.credit, 0) as credit
            FROM members m
            WHERE m.status = 'active'
              AND (m.name ILIKE %s OR m.phone ILIKE %s OR m.username ILIKE %s)
            ORDER BY m.name
        ''', (get_expected_total(), get_expected_total(), f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
                cur.execute('''
            SELECT m.*,
                   (SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) as total_paid,
                   (SELECT COUNT(*) FROM contributions c WHERE c.member_id = m.id) as weeks_paid,
                   %s as expected_total,
                   ((SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) + COALESCE(m.credit, 0) - %s) as balance,
                   COALESCE(m.credit, 0) as credit
            FROM members m
            WHERE m.status = 'active'
            ORDER BY m.name
        ''', (get_expected_total(), get_expected_total()))
        ''')

    members_list = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('members.html', members=members_list, search_query=search_query)
@app.route('/member/<int:member_id>')
@admin_required
def member_detail(member_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Get member info and totals
       cur.execute('''
        SELECT m.*,
               (SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) as total_paid,
               (SELECT COUNT(*) FROM contributions c WHERE c.member_id = m.id) as weeks_paid,
               %s as expected_total,
               ((SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) + COALESCE(m.credit, 0) - %s) as balance,
               COALESCE(m.credit, 0) as credit
        FROM members m
        WHERE m.id = %s
    ''', (get_expected_total(), get_expected_total(), member_id))
    member = cur.fetchone()
    
    if not member:
        flash('Member not found!', 'error')
        return redirect(url_for('members'))
    
    # Get all contributions for this member
    cur.execute('''
        SELECT id, amount, week_start, date_paid
        FROM contributions
        WHERE member_id = %s
        ORDER BY week_start DESC
    ''', (member_id,))
    contributions = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('member_detail.html', member=member, contributions=contributions)

@app.route('/add_member', methods=['POST'])
@app.route('/add_member', methods=['POST'])
@admin_required
def add_member():
    name = request.form.get('name')
    phone = request.form.get('phone', '')
    username = request.form.get('username')
    password = request.form.get('password')
    
    if name and username and password:
        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('members'))
        hashed = generate_password_hash(password)
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO members (name, phone, username, password_hash) VALUES (%s, %s, %s, %s)",
                        (name, phone, username, hashed))
            conn.commit()
            flash('Member added successfully! They can log in with their username and password.', 'success')
        except Exception as e:
            conn.rollback()
            flash('Error: Username may already exist. Please choose a different username.', 'error')
        finally:
            cur.close()
            conn.close()
    else:
        flash('Name, username, and password are required!', 'error')
    return redirect(url_for('members'))

@app.route('/delete_member/<int:member_id>')
@admin_required
def delete_member(member_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM members WHERE id = %s", (member_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Member deleted!', 'success')
    return redirect(url_for('members'))
@app.route('/deactivate_member/<int:member_id>')
@admin_required
def deactivate_member(member_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE members SET status = 'inactive' WHERE id = %s", (member_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Member deactivated successfully. Their history is preserved.', 'success')
    return redirect(url_for('members'))

@app.route('/contributions')
@admin_required
def contributions():
    current_week = get_current_week_start()
    week_filter = request.args.get('week', current_week)

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM members WHERE status='active' ORDER BY name")
    members_list = cur.fetchall()

    # If filtering by a specific week, only show contributions for that week
    cur.execute('''
        SELECT member_id FROM contributions
        WHERE week_start = %s
    ''', (week_filter,))
    paid_this_week = cur.fetchall()
    paid_ids = [row['member_id'] for row in paid_this_week]

    cur.execute('''
        SELECT c.id, m.name, c.amount, c.week_start, c.date_paid
        FROM contributions c
        JOIN members m ON c.member_id = m.id
        WHERE c.week_start = %s
        ORDER BY c.date_paid DESC
    ''', (week_filter,))
    history = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('contributions.html',
                         members=members_list,
                         paid_ids=paid_ids,
                         current_week=current_week,
                         week_filter=week_filter,
                         history=history)

@app.route('/record_contribution', methods=['POST'])
@admin_required
def record_contribution():
    member_id = request.form.get('member_id')
    amount = float(request.form.get('amount', 0))
    week_start = request.form.get('week_start', get_current_week_start())

    if not member_id:
        flash('Please select a member!', 'error')
        return redirect(url_for('contributions'))

    if amount <= 0:
        flash('Amount must be greater than zero.', 'error')
        return redirect(url_for('contributions'))

    full_weeks = int(amount // 50)
    remainder = amount - (full_weeks * 50)

    if full_weeks == 0:
        # amount is less than 50, treat as credit only
        remainder = amount
        full_weeks = 0

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    inserted = 0
    for i in range(full_weeks):
        week_date = datetime.strptime(week_start, '%Y-%m-%d').date() + timedelta(weeks=i)
        week_str = week_date.strftime('%Y-%m-%d')

        cur.execute('''
            SELECT id FROM contributions
            WHERE member_id = %s AND week_start = %s
        ''', (member_id, week_str))
        existing = cur.fetchone()
        if existing:
            continue

        cur.execute('''
            INSERT INTO contributions (member_id, amount, week_start)
            VALUES (%s, %s, %s)
        ''', (member_id, 50.0, week_str))
        inserted += 1

    # Handle remainder as credit
    if remainder > 0:
        cur.execute("UPDATE members SET credit = credit + %s WHERE id = %s", (remainder, member_id))
        credit_added = True
    else:
        credit_added = False

    conn.commit()
    cur.close()
    conn.close()

    if inserted > 0 and credit_added:
        flash(f'Recorded {inserted} week(s) and added KSH {remainder:.0f} credit.', 'success')
    elif inserted > 0:
        flash(f'Recorded {inserted} week(s) successfully.', 'success')
    elif credit_added:
        flash(f'Added KSH {remainder:.0f} credit (less than one week).', 'success')
    else:
        flash('All selected weeks were already paid.', 'error')

    return redirect(url_for('contributions'))

@app.route('/delete_contribution/<int:contribution_id>')
@admin_required
def delete_contribution(contribution_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM contributions WHERE id = %s", (contribution_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Contribution deleted!', 'success')
    return redirect(url_for('contributions'))

@app.route('/expenses')
@admin_required
def expenses():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('''
        SELECT * FROM expenses
        ORDER BY expense_date DESC
    ''')
    expenses_list = cur.fetchall()

    cur.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses
        GROUP BY category
    ''')
    categories = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('expenses.html',
                         expenses=expenses_list,
                         categories=categories)

@app.route('/add_expense', methods=['POST'])
@admin_required
def add_expense():
    description = request.form.get('description')
    amount = request.form.get('amount')
    category = request.form.get('category', 'Other')
    expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
    recorded_by = request.form.get('recorded_by', 'Admin')

    if description and amount:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO expenses (description, amount, category, expense_date, recorded_by)
            VALUES (%s, %s, %s, %s, %s)
        ''', (description, amount, category, expense_date, recorded_by))
        conn.commit()
        cur.close()
        conn.close()
        flash('Expense added successfully!', 'success')
    else:
        flash('Description and amount are required!', 'error')

    return redirect(url_for('expenses'))

@app.route('/delete_expense/<int:expense_id>')
@admin_required
def delete_expense(expense_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
    conn.commit()
    cur.close()
    conn.close()
    flash('Expense deleted!', 'success')
    return redirect(url_for('expenses'))

@app.route('/reports')
@admin_required
def reports():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('''
        SELECT to_char(date_paid, 'YYYY-MM') as month, SUM(amount) as total
        FROM contributions
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    ''')
    monthly_data = cur.fetchall()

    cur.execute('''
        SELECT to_char(expense_date, 'YYYY-MM') as month, SUM(amount) as total
        FROM expenses
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    ''')
    monthly_expenses = cur.fetchall()

    cur.execute('''
        SELECT m.name,
               COUNT(c.id) as weeks_paid,
               SUM(c.amount) as total_paid
        FROM members m
        LEFT JOIN contributions c ON m.id = c.member_id
        WHERE m.is_admin = FALSE
        GROUP BY m.id
        ORDER BY total_paid DESC
    ''')
    member_stats = cur.fetchall()

    cur.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses
        GROUP BY category
        ORDER BY total DESC
    ''')
    expense_categories = cur.fetchall()
    cur.close()
    conn.close()

    months = [row['month'] for row in monthly_data]
    contributions_amounts = [row['total'] for row in monthly_data]
    expenses_amounts = [row['total'] for row in monthly_expenses]

    return render_template('reports.html',
                         monthly_data=monthly_data,
                         monthly_expenses=monthly_expenses,
                         member_stats=member_stats,
                         expense_categories=expense_categories,
                         months=json.dumps(months),
                         contributions_amounts=json.dumps(contributions_amounts),
                         expenses_amounts=json.dumps(expenses_amounts))

init_db()
@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_password or not new_password or not confirm_password:
            flash('All fields are required.', 'error')
            return redirect(url_for('change_password'))

        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('change_password'))

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM members WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user or not check_password_hash(user['password_hash'], current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('change_password'))

        # Hash the new password
        new_hash = generate_password_hash(new_password)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE members SET password_hash = %s WHERE id = %s", (new_hash, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()
        flash('Password changed successfully!', 'success')
        return redirect(url_for('dashboard'))

    return render_template('change_password.html')

@app.route('/my_profile', methods=['GET', 'POST'])
@login_required
def my_profile():
    user_id = session['user_id']
    if request.method == 'POST':
        phone = request.form.get('phone', '')
        username = request.form.get('username', '').strip()

        if not username:
            flash('Username cannot be empty.', 'error')
            return redirect(url_for('my_profile'))

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Check if username is taken by another member
        cur.execute("SELECT id FROM members WHERE username = %s AND id != %s", (username, user_id))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            flash('Username already taken by another member. Please choose a different one.', 'error')
            return redirect(url_for('my_profile'))

        # Update phone and username
        cur.execute("UPDATE members SET phone = %s, username = %s WHERE id = %s",
                    (phone, username, user_id))
        conn.commit()
        cur.close()
        conn.close()

        # Update session username immediately
        session['username'] = username
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    else:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM members WHERE id = %s", (user_id,))
        member = cur.fetchone()
        cur.close()
        conn.close()
        return render_template('my_profile.html', member=member)
@app.route('/edit_member/<int:member_id>', methods=['GET', 'POST'])
@admin_required
def edit_member(member_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM members WHERE id = %s", (member_id,))
    member = cur.fetchone()
    cur.close()
    conn.close()

    if not member:
        flash('Member not found!', 'error')
        return redirect(url_for('members'))

    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone', '')
        username = request.form.get('username')
        new_password = request.form.get('new_password', '')

        if not name or not username:
            flash('Name and username are required.', 'error')
            return redirect(url_for('edit_member', member_id=member_id))

        # Check if username is taken by another member
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM members WHERE username = %s AND id != %s", (username, member_id))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            flash('Username already taken by another member.', 'error')
            return redirect(url_for('edit_member', member_id=member_id))

        # Update member info
        cur.execute("UPDATE members SET name = %s, phone = %s, username = %s WHERE id = %s",
                    (name, phone, username, member_id))
        
         # If new password provided, hash and update it
        if new_password:
            if len(new_password) < 6:
                flash('Password must be at least 6 characters long.', 'error')
                return redirect(url_for('edit_member', member_id=member_id))
            hashed = generate_password_hash(new_password)
            cur.execute("UPDATE members SET password_hash = %s WHERE id = %s", (hashed, member_id))

        conn.commit()
        cur.close()
        conn.close()
        flash('Member updated successfully!', 'success')
        return redirect(url_for('members'))

    return render_template('edit_member.html', member=member)
@app.route('/admin_profile', methods=['GET', 'POST'])
@admin_required
def admin_profile():
    # Get current admin details
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM members WHERE id = %s", (session['user_id'],))
    admin = cur.fetchone()
    cur.close()
    conn.close()

    if not admin:
        flash('Admin not found!', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        new_password = request.form.get('new_password', '')

        if not name or not username:
            flash('Name and username are required.', 'error')
            return redirect(url_for('admin_profile'))

        # Check if username is taken by another member
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM members WHERE username = %s AND id != %s", (username, session['user_id']))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            flash('Username already taken by another member.', 'error')
            return redirect(url_for('admin_profile'))

        # Update name and username
        cur.execute("UPDATE members SET name = %s, username = %s WHERE id = %s",
                    (name, username, session['user_id']))

        # If new password provided, update it
        if new_password:
            if len(new_password) < 6:
                flash('Password must be at least 6 characters long.', 'error')
                return redirect(url_for('admin_profile'))
            hashed = generate_password_hash(new_password)
            cur.execute("UPDATE members SET password_hash = %s WHERE id = %s", (hashed, session['user_id']))

        conn.commit()
        cur.close()
        conn.close()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('admin_profile'))

    return render_template('admin_profile.html', admin=admin)
@app.route('/export_contributions')
@admin_required
def export_contributions():
    # Connect to the database
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all contributions with member details
    cur.execute('''
        SELECT m.name, m.phone, m.username, c.amount, c.week_start, c.date_paid
        FROM contributions c
        JOIN members m ON c.member_id = m.id
        ORDER BY c.date_paid DESC
    ''')
    rows = cur.fetchall()   # List of dictionaries
    cur.close()
    conn.close()

    # Create an in-memory text buffer for CSV
    si = StringIO()
    cw = csv.writer(si)

    # Write header row
    cw.writerow(['Member Name', 'Phone', 'Username', 'Amount (KSH)', 'Week Starting', 'Date Paid'])

    # Write each row from the database
    for row in rows:
        cw.writerow([
            row['name'],
            row['phone'] or '',
            row['username'] or '',
            row['amount'],
            row['week_start'],
            row['date_paid']
        ])

    # Get the CSV string
    output = si.getvalue()

    # Return as a downloadable file
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=contributions.csv"}
    )
@app.route('/export_expenses')
@admin_required
def export_expenses():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute('''
        SELECT description, amount, category, expense_date, recorded_by
        FROM expenses
        ORDER BY expense_date DESC
    ''')
    rows = cur.fetchall()
    cur.close()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Description', 'Amount (KSH)', 'Category', 'Date', 'Recorded By'])
    for row in rows:
        cw.writerow([
            row['description'],
            row['amount'],
            row['category'] or '',
            row['expense_date'],
            row['recorded_by'] or ''
        ])

    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=expenses.csv"}
    )

@app.route('/manifest.json')

def manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone', '')
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not name or not username or not password:
            flash('Name, username, and password are required.', 'error')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('register'))

        hashed = generate_password_hash(password)
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM members WHERE username = %s", (username,))
        existing = cur.fetchone()
        if existing:
            cur.close()
            conn.close()
            flash('Username already taken. Please choose another.', 'error')
            return redirect(url_for('register'))

        cur.execute("INSERT INTO members (name, phone, username, password_hash, is_admin) VALUES (%s, %s, %s, %s, FALSE)",
                    (name, phone, username, hashed))
        conn.commit()
        cur.close()
        conn.close()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)