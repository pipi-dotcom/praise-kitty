# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.secret_key = 'praise-team-kitty-2024'

# Database initialization
def init_db():
    conn = sqlite3.connect('kitty.db')
    c = conn.cursor()
    
    # Members table
    c.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            join_date DATE DEFAULT CURRENT_DATE,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Contributions table
    c.execute('''
        CREATE TABLE IF NOT EXISTS contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 50.0,
            week_start DATE NOT NULL,
            date_paid TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id)
        )
    ''')
    
    # Expenses table
    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT,
            expense_date DATE NOT NULL,
            recorded_by TEXT,
            date_recorded TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Helper functions
def get_db():
    conn = sqlite3.connect('kitty.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_total_contributions():
    conn = get_db()
    result = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM contributions").fetchone()
    conn.close()
    return result[0]

def get_total_expenses():
    conn = get_db()
    result = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses").fetchone()
    conn.close()
    return result[0]

def get_active_members_count():
    conn = get_db()
    result = conn.execute("SELECT COUNT(*) FROM members WHERE status='active'").fetchone()
    conn.close()
    return result[0]

def get_current_week_start():
    today = datetime.now()
    return (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')

# Dashboard route
@app.route('/')
def index():
    total_contributions = get_total_contributions()
    total_expenses = get_total_expenses()
    balance = total_contributions - total_expenses
    active_members = get_active_members_count()
    
    # Recent transactions
    conn = get_db()
    recent_contributions = conn.execute('''
        SELECT m.name, c.amount, c.date_paid 
        FROM contributions c
        JOIN members m ON c.member_id = m.id
        ORDER BY c.date_paid DESC LIMIT 5
    ''').fetchall()
    
    recent_expenses = conn.execute('''
        SELECT description, amount, expense_date 
        FROM expenses
        ORDER BY expense_date DESC LIMIT 5
    ''').fetchall()
    conn.close()
    
    return render_template('index.html', 
                         total_contributions=total_contributions,
                         total_expenses=total_expenses,
                         balance=balance,
                         active_members=active_members,
                         recent_contributions=recent_contributions,
                         recent_expenses=recent_expenses)

# Members routes
@app.route('/members')
def members():
    conn = get_db()
    members_list = conn.execute('''
        SELECT m.*, 
               (SELECT COALESCE(SUM(amount), 0) FROM contributions c WHERE c.member_id = m.id) as total_paid,
               (SELECT COUNT(*) FROM contributions c WHERE c.member_id = m.id) as weeks_paid
        FROM members m
        ORDER BY m.name
    ''').fetchall()
    conn.close()
    return render_template('members.html', members=members_list)

@app.route('/add_member', methods=['POST'])
def add_member():
    name = request.form.get('name')
    phone = request.form.get('phone', '')
    
    if name:
        conn = get_db()
        conn.execute("INSERT INTO members (name, phone) VALUES (?, ?)", (name, phone))
        conn.commit()
        conn.close()
        flash('Member added successfully!', 'success')
    else:
        flash('Member name is required!', 'error')
    
    return redirect(url_for('members'))

@app.route('/delete_member/<int:member_id>')
def delete_member(member_id):
    conn = get_db()
    conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    flash('Member deleted!', 'success')
    return redirect(url_for('members'))

# Contributions routes
@app.route('/contributions')
def contributions():
    current_week = get_current_week_start()
    conn = get_db()
    members_list = conn.execute("SELECT * FROM members WHERE status='active' ORDER BY name").fetchall()
    
    # Check who has paid this week
    paid_this_week = conn.execute('''
        SELECT member_id FROM contributions 
        WHERE week_start = ?
    ''', (current_week,)).fetchall()
    
    paid_ids = [row['member_id'] for row in paid_this_week]
    
    # Get all contributions history
    history = conn.execute('''
        SELECT c.id, m.name, c.amount, c.week_start, c.date_paid
        FROM contributions c
        JOIN members m ON c.member_id = m.id
        ORDER BY c.date_paid DESC
        LIMIT 50
    ''').fetchall()
    
    conn.close()
    
    return render_template('contributions.html', 
                         members=members_list,
                         paid_ids=paid_ids,
                         current_week=current_week,
                         history=history)

@app.route('/record_contribution', methods=['POST'])
def record_contribution():
    member_id = request.form.get('member_id')
    amount = request.form.get('amount', 50)
    week_start = request.form.get('week_start', get_current_week_start())
    
    if member_id:
        conn = get_db()
        # Check if already paid this week
        existing = conn.execute('''
            SELECT id FROM contributions 
            WHERE member_id = ? AND week_start = ?
        ''', (member_id, week_start)).fetchone()
        
        if existing:
            flash('This member has already paid for this week!', 'error')
        else:
            conn.execute('''
                INSERT INTO contributions (member_id, amount, week_start) 
                VALUES (?, ?, ?)
            ''', (member_id, amount, week_start))
            conn.commit()
            flash('Contribution recorded successfully!', 'success')
        conn.close()
    else:
        flash('Please select a member!', 'error')
    
    return redirect(url_for('contributions'))

@app.route('/delete_contribution/<int:contribution_id>')
def delete_contribution(contribution_id):
    conn = get_db()
    conn.execute("DELETE FROM contributions WHERE id = ?", (contribution_id,))
    conn.commit()
    conn.close()
    flash('Contribution deleted!', 'success')
    return redirect(url_for('contributions'))

# Expenses routes
@app.route('/expenses')
def expenses():
    conn = get_db()
    expenses_list = conn.execute('''
        SELECT * FROM expenses 
        ORDER BY expense_date DESC
    ''').fetchall()
    
    # Group expenses by category
    categories = conn.execute('''
        SELECT category, SUM(amount) as total 
        FROM expenses 
        GROUP BY category
    ''').fetchall()
    conn.close()
    
    return render_template('expenses.html', 
                         expenses=expenses_list,
                         categories=categories)

@app.route('/add_expense', methods=['POST'])
def add_expense():
    description = request.form.get('description')
    amount = request.form.get('amount')
    category = request.form.get('category', 'Other')
    expense_date = request.form.get('expense_date', datetime.now().strftime('%Y-%m-%d'))
    recorded_by = request.form.get('recorded_by', 'Admin')
    
    if description and amount:
        conn = get_db()
        conn.execute('''
            INSERT INTO expenses (description, amount, category, expense_date, recorded_by) 
            VALUES (?, ?, ?, ?, ?)
        ''', (description, amount, category, expense_date, recorded_by))
        conn.commit()
        conn.close()
        flash('Expense added successfully!', 'success')
    else:
        flash('Description and amount are required!', 'error')
    
    return redirect(url_for('expenses'))

@app.route('/delete_expense/<int:expense_id>')
def delete_expense(expense_id):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    conn.close()
    flash('Expense deleted!', 'success')
    return redirect(url_for('expenses'))

# Reports route
@app.route('/reports')
def reports():
    # Monthly summary
    conn = get_db()
    monthly_data = conn.execute('''
        SELECT 
            strftime('%Y-%m', date_paid) as month,
            SUM(amount) as total
        FROM contributions
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    ''').fetchall()
    
    monthly_expenses = conn.execute('''
        SELECT 
            strftime('%Y-%m', expense_date) as month,
            SUM(amount) as total
        FROM expenses
        GROUP BY month
        ORDER BY month DESC
        LIMIT 12
    ''').fetchall()
    
    # Member performance
    member_stats = conn.execute('''
        SELECT m.name, 
               COUNT(c.id) as weeks_paid,
               SUM(c.amount) as total_paid
        FROM members m
        LEFT JOIN contributions c ON m.id = c.member_id
        GROUP BY m.id
        ORDER BY total_paid DESC
    ''').fetchall()
    
    # Expense breakdown
    expense_categories = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses
        GROUP BY category
        ORDER BY total DESC
    ''').fetchall()
    conn.close()
    
    # Prepare data for charts
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

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)