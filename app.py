from flask import Flask, render_template, request, redirect, flash, session, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras
import datetime
import json
import csv
import io
import calendar
import os
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "expense-manager-secret-key")

CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥"
}

_db_initialized = False


def get_db_connection():
    global _db_initialized
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not configured. Please set DATABASE_URL in your environment or Vercel project settings.")
    
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.DictCursor)
    
    if not _db_initialized:
        try:
            init_db_with_conn(conn)
            _db_initialized = True
        except Exception as e:
            print(f"Error initializing DB schema: {e}")
            
    return conn


def init_db_with_conn(conn):
    with conn.cursor() as cursor:
        # Create users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                email VARCHAR(255) NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create expenses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                amount DOUBLE PRECISION NOT NULL,
                category VARCHAR(255) NOT NULL,
                description TEXT,
                date VARCHAR(50) NOT NULL,
                payment_method VARCHAR(100) DEFAULT 'Cash'
            )
        """)

        # Create income table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS income (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                amount DOUBLE PRECISION NOT NULL,
                category VARCHAR(255) NOT NULL,
                description TEXT,
                date VARCHAR(50) NOT NULL,
                payment_method VARCHAR(100) DEFAULT 'Cash'
            )
        """)

        # Create user_settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                key VARCHAR(255) NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)

        # Create categories table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                icon VARCHAR(50) DEFAULT '📦'
            )
        """)

        # Create payment_methods table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payment_methods (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                icon VARCHAR(50) DEFAULT '💳'
            )
        """)

        # Alter table migrations if columns exist from previous runs
        cursor.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        cursor.execute("ALTER TABLE income ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        cursor.execute("ALTER TABLE categories ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
        cursor.execute("ALTER TABLE payment_methods ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")

        conn.commit()


def ensure_user_defaults(conn, user_id):
    with conn.cursor() as cursor:
        # Default user settings
        cursor.execute("INSERT INTO user_settings (user_id, key, value) VALUES (%s, 'currency', 'INR') ON CONFLICT DO NOTHING", (user_id,))
        cursor.execute("INSERT INTO user_settings (user_id, key, value) VALUES (%s, 'monthly_budget', '10000.00') ON CONFLICT DO NOTHING", (user_id,))

        # Check categories count
        cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = %s", (user_id,))
        if cursor.fetchone()[0] == 0:
            default_categories = [
                (user_id, "Food", "🍔"),
                (user_id, "Shopping", "🛍️"),
                (user_id, "Travel", "🚗"),
                (user_id, "Bills", "🧾"),
                (user_id, "Entertainment", "🎮"),
                (user_id, "Health", "🏥"),
                (user_id, "Education", "🎓"),
                (user_id, "Other", "📦")
            ]
            cursor.executemany("INSERT INTO categories (user_id, name, icon) VALUES (%s, %s, %s)", default_categories)

        # Check payment methods count
        cursor.execute("SELECT COUNT(*) FROM payment_methods WHERE user_id = %s", (user_id,))
        if cursor.fetchone()[0] == 0:
            default_payments = [
                (user_id, "Cash", "💵"),
                (user_id, "UPI", "📱"),
                (user_id, "Bank Transfer", "🏦"),
                (user_id, "Card", "💳"),
                (user_id, "Other", "💰")
            ]
            cursor.executemany("INSERT INTO payment_methods (user_id, name, icon) VALUES (%s, %s, %s)", default_payments)

        conn.commit()


def create_default_user_data(conn, user_id):
    ensure_user_defaults(conn, user_id)


def init_db():
    if os.environ.get("DATABASE_URL"):
        try:
            conn = get_db_connection()
            conn.close()
        except Exception as e:
            print(f"init_db error: {e}")


def get_setting(user_id, key, default):
    if not user_id:
        return default
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT value FROM user_settings WHERE user_id = %s AND key = %s", (user_id, key))
    row = cursor.fetchone()
    connection.close()
    if row:
        return row[0]
    return default


def set_setting(user_id, key, value):
    if not user_id:
        return
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        "INSERT INTO user_settings (user_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
        (user_id, key, str(value))
    )
    connection.commit()
    connection.close()


def get_currency_info(user_id):
    currency_code = get_setting(user_id, "currency", "INR")
    currency_symbol = CURRENCY_SYMBOLS.get(currency_code, "₹")
    return currency_code, currency_symbol


def get_sorted_payment_methods(cursor, user_id):
    cursor.execute("SELECT * FROM payment_methods WHERE user_id = %s", (user_id,))
    rows = cursor.fetchall()
    order_map = {"Cash": 1, "UPI": 2, "Bank Transfer": 3, "Card": 4, "Other": 5}
    return sorted(rows, key=lambda x: order_map.get(x["name"], 99))


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access Expense Manager.", "error")
            return redirect("/login")
        
        user_id = session["user_id"]
        try:
            conn = get_db_connection()
            ensure_user_defaults(conn, user_id)
            conn.close()
        except Exception as e:
            print(f"ensure_user_defaults error: {e}")
            
        return f(*args, **kwargs)
    return decorated_function


def get_filter_dates():
    now = datetime.datetime.now()
    today = now.date()
    
    filter_range = request.args.get("range", "").strip().lower()
    if filter_range:
        session["filter_range"] = filter_range
    else:
        filter_range = session.get("filter_range", "this_month")
        
    if filter_range not in ["today", "this_week", "this_month", "last_month", "this_year", "custom"]:
        filter_range = "this_month"
        
    selected_month = request.args.get("month", "").strip()
    if selected_month:
        session["selected_month"] = selected_month
    else:
        selected_month = session.get("selected_month", now.strftime("%Y-%m"))
        
    try:
        parsed_date = datetime.datetime.strptime(selected_month, "%Y-%m")
    except ValueError:
        selected_month = now.strftime("%Y-%m")
        parsed_date = now

    if filter_range == "today":
        start_date = today.strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")
        range_label = "Today"
    elif filter_range == "this_week":
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)
        start_date = start_of_week.strftime("%Y-%m-%d")
        end_date = end_of_week.strftime("%Y-%m-%d")
        range_label = "This Week"
    elif filter_range == "this_month":
        start_date = today.replace(day=1).strftime("%Y-%m-%d")
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        last_day = next_month - datetime.timedelta(days=next_month.day)
        end_date = last_day.strftime("%Y-%m-%d")
        range_label = today.strftime("%B %Y")
    elif filter_range == "last_month":
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - datetime.timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        start_date = first_day_last_month.strftime("%Y-%m-%d")
        end_date = last_day_last_month.strftime("%Y-%m-%d")
        range_label = last_day_last_month.strftime("%B %Y")
    elif filter_range == "this_year":
        start_date = today.replace(month=1, day=1).strftime("%Y-%m-%d")
        end_date = today.replace(month=12, day=31).strftime("%Y-%m-%d")
        range_label = today.strftime("%Y")
    else: # custom
        first_day = parsed_date.date().replace(day=1)
        next_month = first_day.replace(day=28) + datetime.timedelta(days=4)
        last_day = next_month - datetime.timedelta(days=next_month.day)
        start_date = first_day.strftime("%Y-%m-%d")
        end_date = last_day.strftime("%Y-%m-%d")
        range_label = parsed_date.strftime("%B %Y")
        
    return start_date, end_date, filter_range, selected_month, range_label


# =========================================
# AUTH ROUTES
# =========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect("/")

    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")

        if not username_or_email or not password:
            flash("Please enter both username/email and password.", "error")
            return render_template("login.html")

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)",
            (username_or_email, username_or_email)
        )
        user = cursor.fetchone()
        connection.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["email"] = user["email"]
            flash(f"Welcome back, {user['username']}! 👋", "success")
            return redirect("/")
        else:
            flash("Invalid username/email or password.", "error")

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect("/")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or not email or not password:
            flash("Please fill in all required fields.", "error")
            return render_template("signup.html")

        if len(username) < 3:
            flash("Username must be at least 3 characters long.", "error")
            return render_template("signup.html")

        if "@" not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        connection = get_db_connection()
        cursor = connection.cursor()

        # Check existing user
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s)",
            (username, email)
        )
        if cursor.fetchone()[0] > 0:
            connection.close()
            flash("Username or Email is already registered. Please log in.", "error")
            return render_template("signup.html")

        # Create user
        pwd_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (username, email, pwd_hash)
        )
        user_id = cursor.fetchone()[0]
        connection.commit()

        # Seed initial user settings, categories, payment methods
        create_default_user_data(connection, user_id)
        connection.close()

        # Auto log in user
        session["user_id"] = user_id
        session["username"] = username
        session["email"] = email
        flash(f"Account created successfully! Welcome, {username}! 🎉", "success")
        return redirect("/")

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect("/login")


# =========================================
# APP MAIN DASHBOARD & VIEW ROUTES
# =========================================

@app.route("/")
@login_required
def home():
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    # Calculate Total Expenses (All-time for this user)
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s", (user_id,))
    total_expenses = cursor.fetchone()["total"] or 0

    # Calculate Total Income (All-time for this user)
    cursor.execute("SELECT SUM(amount) AS total FROM income WHERE user_id = %s", (user_id,))
    total_income = cursor.fetchone()["total"] or 0

    # Calculate Total Balance
    balance = total_income - total_expenses

    # Get Date Filter Range bounds using helper
    start_date, end_date, filter_range, selected_month, range_label = get_filter_dates()

    # Calculate Monthly Expenses (for the currently active date range)
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    monthly_expenses = cursor.fetchone()["total"] or 0

    # Calculate Spent Today Expenses
    now = datetime.datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND date = %s", (user_id, today_str))
    today_expenses = cursor.fetchone()["total"] or 0

    # Get Daily Expenses for Chart.js
    cursor.execute("""
        SELECT date, SUM(amount) AS total 
        FROM expenses 
        WHERE user_id = %s AND date BETWEEN %s AND %s
        GROUP BY date 
        ORDER BY date ASC
    """, (user_id, start_date, end_date))
    chart_rows = cursor.fetchall()

    # Format Chart.js Data
    chart_labels = []
    chart_values = []
    months_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for row in chart_rows:
        try:
            d = datetime.datetime.strptime(row["date"], "%Y-%m-%d")
            day_label = f"{d.day} {months_short[d.month - 1]}"
        except ValueError:
            day_label = row["date"]
        chart_labels.append(day_label)
        chart_values.append(float(row["total"]))

    # Fallbacks if chart data is empty
    if not chart_labels:
        try:
            m_idx = int(selected_month.split('-')[1])
            m_short = months_short[m_idx - 1]
        except (ValueError, IndexError):
            m_short = "Aug"
        chart_labels = [f"1 {m_short}", f"5 {m_short}", f"10 {m_short}", f"15 {m_short}", f"20 {m_short}", f"25 {m_short}", f"31 {m_short}"]
        chart_values = [0, 0, 0, 0, 0, 0, 0]

    chart_labels_json = json.dumps(chart_labels)
    chart_values_json = json.dumps(chart_values)

    # Fetch dynamic currency settings
    currency_code, currency_symbol = get_currency_info(user_id)

    # Fetch budget settings
    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0

    # Get Expenses for the SELECTED date range
    cursor.execute("""
        SELECT e.*, c.icon AS category_icon
        FROM expenses e
        LEFT JOIN categories c ON (e.category = c.name AND c.user_id = e.user_id)
        WHERE e.user_id = %s AND e.date BETWEEN %s AND %s
        ORDER BY e.date DESC, e.id DESC
    """, (user_id, start_date, end_date))
    expenses = cursor.fetchall()

    connection.close()

    return render_template(
        "dashboard.html",
        total_expenses=total_expenses,
        total_income=total_income,
        balance=balance,
        monthly_expenses=monthly_expenses,
        today_expenses=today_expenses,
        selected_month=selected_month,
        selected_month_name=range_label,
        filter_range=filter_range,
        chart_labels_json=chart_labels_json,
        chart_values_json=chart_values_json,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        currency_symbol=currency_symbol,
        expenses=expenses
    )


@app.route("/add-expense", methods=["GET", "POST"])
@login_required
def add_expense():
    user_id = session["user_id"]
    if request.method == "POST":
        amount = request.form["amount"]
        category = request.form["category"]
        description = request.form["description"]
        date = request.form["date"]
        payment_method = request.form.get("payment_method", "Cash")

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO expenses
            (user_id, amount, category, description, date, payment_method)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, amount, category, description, date, payment_method))
        connection.commit()
        connection.close()

        flash("Expense added successfully! 💸", "success")
        return redirect("/")

    # Fetch options dynamically
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("SELECT * FROM categories WHERE user_id = %s ORDER BY name ASC", (user_id,))
    categories = cursor.fetchall()
    
    payment_methods = get_sorted_payment_methods(cursor, user_id)

    # Monthly overview sidebar metrics
    now = datetime.datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_month_name = now.strftime("%B %Y")
    
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0
    connection.close()

    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0
    _, currency_symbol = get_currency_info(user_id)

    return render_template(
        "add_expense.html",
        current_month_name=current_month_name,
        monthly_expenses=monthly_expenses,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        categories=categories,
        payment_methods=payment_methods,
        currency_symbol=currency_symbol
    )


@app.route("/add-income", methods=["GET", "POST"])
@login_required
def add_income():
    user_id = session["user_id"]
    if request.method == "POST":
        amount = request.form["amount"]
        category = request.form["category"]
        description = request.form["description"]
        date = request.form["date"]
        payment_method = request.form.get("payment_method", "Cash")

        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("""
            INSERT INTO income
            (user_id, amount, category, description, date, payment_method)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, amount, category, description, date, payment_method))
        connection.commit()
        connection.close()

        flash("Income added successfully! 💰", "success")
        return redirect("/")

    # Fetch options dynamically
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("SELECT * FROM categories WHERE user_id = %s ORDER BY name ASC", (user_id,))
    categories = cursor.fetchall()
    
    payment_methods = get_sorted_payment_methods(cursor, user_id)

    # Monthly overview sidebar metrics
    now = datetime.datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_month_name = now.strftime("%B %Y")
    
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0
    connection.close()

    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0
    _, currency_symbol = get_currency_info(user_id)

    return render_template(
        "add_income.html",
        current_month_name=current_month_name,
        monthly_expenses=monthly_expenses,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        categories=categories,
        payment_methods=payment_methods,
        currency_symbol=currency_symbol
    )


@app.route("/delete-expense/<int:expense_id>", methods=["POST"])
@login_required
def delete_expense(expense_id):
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense_id, user_id))
    connection.commit()
    connection.close()
    flash("Expense deleted.", "info")
    return redirect(request.referrer or "/")


@app.route("/delete-income/<int:income_id>", methods=["POST"])
@login_required
def delete_income(income_id):
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute("DELETE FROM income WHERE id = %s AND user_id = %s", (income_id, user_id))
    connection.commit()
    connection.close()
    flash("Income deleted.", "info")
    return redirect(request.referrer or "/")


# =========================================
# SETTINGS PAGE ROUTES
# =========================================

@app.route("/settings")
@login_required
def settings():
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    # Fetch settings data
    currency_code, currency_symbol = get_currency_info(user_id)
    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))

    # Fetch monthly spending aggregates
    now = datetime.datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_month_name = now.strftime("%B %Y")
    
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0

    # Calculate remaining budget and percentage
    remaining_budget = budget_limit - monthly_expenses
    budget_percent = (monthly_expenses / budget_limit) * 100 if budget_limit > 0 else 0
    budget_percent_capped = min(100, int(budget_percent))

    # Fetch categories and payment methods
    cursor.execute("SELECT * FROM categories WHERE user_id = %s ORDER BY name ASC", (user_id,))
    categories = cursor.fetchall()

    payment_methods = get_sorted_payment_methods(cursor, user_id)

    connection.close()

    return render_template(
        "settings.html",
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        budget_limit=budget_limit,
        monthly_expenses=monthly_expenses,
        remaining_budget=remaining_budget,
        budget_percent=budget_percent,
        budget_percent_capped=budget_percent_capped,
        current_month_name=current_month_name,
        categories=categories,
        payment_methods=payment_methods
    )


@app.route("/settings/currency", methods=["POST"])
@login_required
def update_currency():
    user_id = session["user_id"]
    new_currency = request.form.get("currency")
    if new_currency in CURRENCY_SYMBOLS:
        set_setting(user_id, "currency", new_currency)
        flash("Default currency updated successfully.", "success")
    else:
        flash("Invalid currency selection.", "error")
    return redirect("/settings")


@app.route("/settings/budget", methods=["POST"])
@login_required
def update_budget():
    user_id = session["user_id"]
    try:
        budget_val = float(request.form["monthly_budget"])
        if budget_val < 0:
            flash("Budget amount cannot be negative.", "error")
        else:
            set_setting(user_id, "monthly_budget", f"{budget_val:.2f}")
            flash("Monthly budget updated successfully.", "success")
    except ValueError:
        flash("Invalid budget format. Please enter a valid number.", "error")
    return redirect("/settings")


@app.route("/settings/category/add", methods=["POST"])
@login_required
def add_category():
    user_id = session["user_id"]
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "📦").strip()

    if not name:
        flash("Category name cannot be empty.", "error")
        return redirect("/settings")

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("INSERT INTO categories (user_id, name, icon) VALUES (%s, %s, %s)", (user_id, name, icon))
        connection.commit()
        connection.close()
        flash(f"Category '{name}' added successfully.", "success")
    except psycopg2.IntegrityError:
        flash("A category with this name already exists.", "error")
    
    return redirect("/settings")


@app.route("/settings/category/edit/<int:cat_id>", methods=["POST"])
@login_required
def edit_category(cat_id):
    user_id = session["user_id"]
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "📦").strip()

    if not name:
        flash("Category name cannot be empty.", "error")
        return redirect("/settings")

    connection = get_db_connection()
    cursor = connection.cursor()
    
    # Get original category name
    cursor.execute("SELECT name FROM categories WHERE id = %s AND user_id = %s", (cat_id, user_id))
    orig_row = cursor.fetchone()
    
    if orig_row:
        orig_name = orig_row[0]
        try:
            cursor.execute("UPDATE categories SET name = %s, icon = %s WHERE id = %s AND user_id = %s", (name, icon, cat_id, user_id))
            
            if orig_name != name:
                cursor.execute("UPDATE expenses SET category = %s WHERE category = %s AND user_id = %s", (name, orig_name, user_id))
                cursor.execute("UPDATE income SET category = %s WHERE category = %s AND user_id = %s", (name, orig_name, user_id))
                
            connection.commit()
            flash("Category details updated successfully.", "success")
        except psycopg2.IntegrityError:
            flash("A category with this name already exists.", "error")
            
    connection.close()
    return redirect("/settings")


@app.route("/settings/category/delete/<int:cat_id>", methods=["POST"])
@login_required
def delete_category(cat_id):
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT name FROM categories WHERE id = %s AND user_id = %s", (cat_id, user_id))
    cat_row = cursor.fetchone()

    if cat_row:
        cat_name = cat_row[0]
        cursor.execute("SELECT COUNT(*) FROM expenses WHERE category = %s AND user_id = %s", (cat_name, user_id))
        expense_use = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM income WHERE category = %s AND user_id = %s", (cat_name, user_id))
        income_use = cursor.fetchone()[0]

        if expense_use > 0 or income_use > 0:
            flash("This category is being used by existing transactions.", "error")
        else:
            cursor.execute("DELETE FROM categories WHERE id = %s AND user_id = %s", (cat_id, user_id))
            connection.commit()
            flash("Category deleted successfully.", "success")

    connection.close()
    return redirect("/settings")


@app.route("/settings/payment/add", methods=["POST"])
@login_required
def add_payment_method():
    user_id = session["user_id"]
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "💳").strip()

    if not name:
        flash("Payment method name cannot be empty.", "error")
        return redirect("/settings")

    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("INSERT INTO payment_methods (user_id, name, icon) VALUES (%s, %s, %s)", (user_id, name, icon))
        connection.commit()
        connection.close()
        flash(f"Payment method '{name}' added successfully.", "success")
    except psycopg2.IntegrityError:
        flash("A payment method with this name already exists.", "error")

    return redirect("/settings")


@app.route("/settings/payment/edit/<int:pay_id>", methods=["POST"])
@login_required
def edit_payment_method(pay_id):
    user_id = session["user_id"]
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "💳").strip()

    if not name:
        flash("Payment method name cannot be empty.", "error")
        return redirect("/settings")

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT name FROM payment_methods WHERE id = %s AND user_id = %s", (pay_id, user_id))
    orig_row = cursor.fetchone()

    if orig_row:
        orig_name = orig_row[0]
        try:
            cursor.execute("UPDATE payment_methods SET name = %s, icon = %s WHERE id = %s AND user_id = %s", (name, icon, pay_id, user_id))
            
            if orig_name != name:
                cursor.execute("UPDATE expenses SET payment_method = %s WHERE payment_method = %s AND user_id = %s", (name, orig_name, user_id))
                cursor.execute("UPDATE income SET payment_method = %s WHERE payment_method = %s AND user_id = %s", (name, orig_name, user_id))
                
            connection.commit()
            flash("Payment method details updated successfully.", "success")
        except psycopg2.IntegrityError:
            flash("A payment method with this name already exists.", "error")

    connection.close()
    return redirect("/settings")


@app.route("/settings/payment/delete/<int:pay_id>", methods=["POST"])
@login_required
def delete_payment_method(pay_id):
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT name FROM payment_methods WHERE id = %s AND user_id = %s", (pay_id, user_id))
    pay_row = cursor.fetchone()

    if pay_row:
        pay_name = pay_row[0]
        cursor.execute("SELECT COUNT(*) FROM expenses WHERE payment_method = %s AND user_id = %s", (pay_name, user_id))
        expense_use = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM income WHERE payment_method = %s AND user_id = %s", (pay_name, user_id))
        income_use = cursor.fetchone()[0]

        if expense_use > 0 or income_use > 0:
            flash("This payment method is being used by existing transactions.", "error")
        else:
            cursor.execute("DELETE FROM payment_methods WHERE id = %s AND user_id = %s", (pay_id, user_id))
            connection.commit()
            flash("Payment method deleted successfully.", "success")

    connection.close()
    return redirect("/settings")


# =========================================
# SIDEBAR NAVIGATION VIEW ROUTES
# =========================================

@app.route("/transactions")
@login_required
def transactions_view():
    user_id = session["user_id"]
    filter_type = request.args.get("type", "all").strip().lower()
    
    connection = get_db_connection()
    cursor = connection.cursor()
    
    # 1. Fetch filtered transactions
    if filter_type == "expense":
        query = """
            SELECT e.id, e.amount, e.category, e.description, e.date, e.payment_method, 'expense' AS type, c.icon AS category_icon
            FROM expenses e
            LEFT JOIN categories c ON (e.category = c.name AND c.user_id = e.user_id)
            WHERE e.user_id = %s
            ORDER BY e.date DESC, e.id DESC
        """
        params = (user_id,)
    elif filter_type == "income":
        query = """
            SELECT i.id, i.amount, i.category, i.description, i.date, i.payment_method, 'income' AS type, c.icon AS category_icon
            FROM income i
            LEFT JOIN categories c ON (i.category = c.name AND c.user_id = i.user_id)
            WHERE i.user_id = %s
            ORDER BY i.date DESC, i.id DESC
        """
        params = (user_id,)
    else:
        query = """
            SELECT t.id, t.amount, t.category, t.description, t.date, t.payment_method, t.type, c.icon AS category_icon
            FROM (
                SELECT id, user_id, amount, category, description, date, payment_method, 'expense' AS type FROM expenses WHERE user_id = %s
                UNION ALL
                SELECT id, user_id, amount, category, description, date, payment_method, 'income' AS type FROM income WHERE user_id = %s
            ) t
            LEFT JOIN categories c ON (t.category = c.name AND c.user_id = t.user_id)
            ORDER BY t.date DESC, t.id DESC
        """
        params = (user_id, user_id)
        
    cursor.execute(query, params)
    transactions = cursor.fetchall()
    
    # 2. Get dynamic overview metrics for sidebar
    now = datetime.datetime.now()
    current_month_str = now.strftime("%Y-%m")
    
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0
    
    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0
    _, currency_symbol = get_currency_info(user_id)
    
    connection.close()
    
    return render_template(
        "transactions.html",
        transactions=transactions,
        filter_type=filter_type,
        monthly_expenses=monthly_expenses,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        currency_symbol=currency_symbol
    )


@app.route("/analytics")
@login_required
def analytics():
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    # Get Date Filter Range bounds using helper
    start_date, end_date, filter_range, selected_month, range_label = get_filter_dates()

    # 1. Total spent in this active date range
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    monthly_expenses = cursor.fetchone()["total"] or 0

    # 2. Total income in this active date range
    cursor.execute("SELECT SUM(amount) AS total FROM income WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    monthly_income = cursor.fetchone()["total"] or 0

    # 3. Category distribution (Expenses only)
    cursor.execute("""
        SELECT e.category, SUM(e.amount) AS total, c.icon AS category_icon
        FROM expenses e
        LEFT JOIN categories c ON (e.category = c.name AND c.user_id = e.user_id)
        WHERE e.user_id = %s AND e.date BETWEEN %s AND %s
        GROUP BY e.category, c.icon
        ORDER BY total DESC
    """, (user_id, start_date, end_date))
    category_data = cursor.fetchall()

    # Form lists for Chart.js
    labels = []
    values = []
    for row in category_data:
        labels.append(f"{row['category_icon'] or '📦'} {row['category']}")
        values.append(float(row["total"]))

    labels_json = json.dumps(labels)
    values_json = json.dumps(values)

    # 4. Key Stats
    # Total Transactions
    cursor.execute("SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    total_transactions = cursor.fetchone()["cnt"] or 0

    # Highest Spending Day
    cursor.execute("""
        SELECT date, SUM(amount) AS daily_sum 
        FROM expenses 
        WHERE user_id = %s AND date BETWEEN %s AND %s 
        GROUP BY date 
        ORDER BY daily_sum DESC 
        LIMIT 1
    """, (user_id, start_date, end_date))
    highest_day_row = cursor.fetchone()
    if highest_day_row:
        highest_day_val = float(highest_day_row["daily_sum"])
        try:
            d_parsed = datetime.datetime.strptime(highest_day_row["date"], "%Y-%m-%d")
            highest_day_label = d_parsed.strftime("%d %b")
        except ValueError:
            highest_day_label = highest_day_row["date"]
    else:
        highest_day_val = 0
        highest_day_label = "N/A"

    # Average Daily Spend
    try:
        dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d")
        days_in_period = max(1, (dt_end - dt_start).days + 1)
    except ValueError:
        days_in_period = 30
    average_daily_spend = float(monthly_expenses) / days_in_period

    # Most Used Category
    cursor.execute("""
        SELECT e.category, COUNT(*) AS cnt, c.icon AS category_icon
        FROM expenses e
        LEFT JOIN categories c ON (e.category = c.name AND c.user_id = e.user_id)
        WHERE e.user_id = %s AND e.date BETWEEN %s AND %s
        GROUP BY e.category, c.icon
        ORDER BY cnt DESC
        LIMIT 1
    """, (user_id, start_date, end_date))
    most_used_cat_row = cursor.fetchone()
    if most_used_cat_row:
        most_used_category = f"{most_used_cat_row['category_icon'] or '📦'} {most_used_cat_row['category']}"
    else:
        most_used_category = "N/A"

    # Most Used Payment Method
    cursor.execute("""
        SELECT e.payment_method, COUNT(*) AS cnt, p.icon AS pm_icon
        FROM expenses e
        LEFT JOIN payment_methods p ON (e.payment_method = p.name AND p.user_id = e.user_id)
        WHERE e.user_id = %s AND e.date BETWEEN %s AND %s
        GROUP BY e.payment_method, p.icon
        ORDER BY cnt DESC
        LIMIT 1
    """, (user_id, start_date, end_date))
    most_used_pm_row = cursor.fetchone()
    if most_used_pm_row:
        most_used_pm = f"{most_used_pm_row['pm_icon'] or '💳'} {most_used_pm_row['payment_method']}"
    else:
        most_used_pm = "N/A"

    # Top Category
    top_category = "N/A"
    if category_data:
        top_category = f"{category_data[0]['category_icon'] or '📦'} {category_data[0]['category']}"

    # Average Expense Transaction
    cursor.execute("SELECT AVG(amount) AS avg_amt FROM expenses WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    avg_expense = cursor.fetchone()["avg_amt"] or 0

    # Largest Expense Transaction
    cursor.execute("SELECT MAX(amount) AS max_amt FROM expenses WHERE user_id = %s AND date BETWEEN %s AND %s", (user_id, start_date, end_date))
    largest_expense = cursor.fetchone()["max_amt"] or 0

    # Sidebar parameters
    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0
    _, currency_symbol = get_currency_info(user_id)

    connection.close()

    return render_template(
        "analytics.html",
        monthly_expenses=monthly_expenses,
        monthly_income=monthly_income,
        category_data=category_data,
        labels_json=labels_json,
        values_json=values_json,
        top_category=top_category,
        avg_expense=avg_expense,
        largest_expense=largest_expense,
        current_month_name=range_label,
        filter_range=filter_range,
        selected_month=selected_month,
        total_transactions=total_transactions,
        highest_day_val=highest_day_val,
        highest_day_label=highest_day_label,
        average_daily_spend=average_daily_spend,
        most_used_category=most_used_category,
        most_used_pm=most_used_pm,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        currency_symbol=currency_symbol
    )


@app.route("/categories")
@login_required
def categories_view():
    user_id = session["user_id"]
    connection = get_db_connection()
    cursor = connection.cursor()

    # Query all categories for this user
    cursor.execute("SELECT * FROM categories WHERE user_id = %s ORDER BY name ASC", (user_id,))
    db_categories = cursor.fetchall()

    categories_list = []
    for cat in db_categories:
        cursor.execute("SELECT COUNT(*) FROM expenses WHERE user_id = %s AND category = %s", (user_id, cat["name"]))
        exp_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM income WHERE user_id = %s AND category = %s", (user_id, cat["name"]))
        inc_count = cursor.fetchone()[0]
        total_count = exp_count + inc_count

        cursor.execute("SELECT SUM(amount) FROM expenses WHERE user_id = %s AND category = %s", (user_id, cat["name"]))
        total_spent = cursor.fetchone()[0] or 0

        categories_list.append({
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat["icon"],
            "count": total_count,
            "total_spent": total_spent
        })

    # Sidebar parameters
    now = datetime.datetime.now()
    current_month_str = now.strftime("%Y-%m")
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0
    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0
    _, currency_symbol = get_currency_info(user_id)

    connection.close()

    return render_template(
        "categories.html",
        categories=categories_list,
        monthly_expenses=monthly_expenses,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        currency_symbol=currency_symbol
    )


# =========================================
# REPORT DOWNLOADS AND PDF/CSV EXPORTS
# =========================================

def compute_report_data(user_id, report_type, target_val):
    connection = get_db_connection()
    cursor = connection.cursor()
    
    total_spent = 0
    num_transactions = 0
    expenses = []
    category_breakdown = []
    day_by_day = []
    avg_daily_spend = 0
    highest_spending_day = 0
    
    if report_type == "daily":
        cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND date = %s", (user_id, target_val))
        total_spent = cursor.fetchone()["total"] or 0
        
        cursor.execute("SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = %s AND date = %s", (user_id, target_val))
        num_transactions = cursor.fetchone()["cnt"] or 0
        
        cursor.execute("""
            SELECT category, SUM(amount) AS total 
            FROM expenses 
            WHERE user_id = %s AND date = %s 
            GROUP BY category 
            ORDER BY total DESC
        """, (user_id, target_val))
        category_breakdown = cursor.fetchall()
        
        cursor.execute("""
            SELECT date, category, description, payment_method, amount 
            FROM expenses 
            WHERE user_id = %s AND date = %s 
            ORDER BY id ASC
        """, (user_id, target_val))
        expenses = cursor.fetchall()
        
    elif report_type == "monthly":
        cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, target_val))
        total_spent = cursor.fetchone()["total"] or 0
        
        cursor.execute("SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, target_val))
        num_transactions = cursor.fetchone()["cnt"] or 0
        
        cursor.execute("""
            SELECT category, SUM(amount) AS total 
            FROM expenses 
            WHERE user_id = %s AND substr(date, 1, 7) = %s 
            GROUP BY category 
            ORDER BY total DESC
        """, (user_id, target_val))
        category_breakdown = cursor.fetchall()
        
        try:
            year, month = map(int, target_val.split('-'))
            days_in_month = calendar.monthrange(year, month)[1]
        except (ValueError, IndexError):
            days_in_month = 30
            
        avg_daily_spend = float(total_spent) / days_in_month
        
        cursor.execute("""
            SELECT date, SUM(amount) AS total 
            FROM expenses 
            WHERE user_id = %s AND substr(date, 1, 7) = %s 
            GROUP BY date 
            ORDER BY total DESC 
            LIMIT 1
        """, (user_id, target_val))
        high_row = cursor.fetchone()
        highest_spending_day = float(high_row["total"]) if high_row else 0
        
        day_sums = {}
        cursor.execute("""
            SELECT date, SUM(amount) AS total 
            FROM expenses 
            WHERE user_id = %s AND substr(date, 1, 7) = %s 
            GROUP BY date
        """, (user_id, target_val))
        for r in cursor.fetchall():
            day_sums[r["date"]] = float(r["total"])
            
        for d in range(1, days_in_month + 1):
            date_str = f"{target_val}-{d:02d}"
            amt = day_sums.get(date_str, 0)
            day_by_day.append({
                "day_label": f"{d} " + calendar.month_abbr[month] if 'month' in locals() else f"{d}",
                "amount": amt
            })
            
        cursor.execute("""
            SELECT date, category, description, payment_method, amount 
            FROM expenses 
            WHERE user_id = %s AND substr(date, 1, 7) = %s 
            ORDER BY date ASC, id ASC
        """, (user_id, target_val))
        expenses = cursor.fetchall()
        
    connection.close()
    
    return {
        "total_spent": total_spent,
        "num_transactions": num_transactions,
        "expenses": expenses,
        "category_breakdown": category_breakdown,
        "day_by_day": day_by_day,
        "avg_daily_spend": avg_daily_spend,
        "highest_spending_day": highest_spending_day
    }


@app.route("/downloads")
@login_required
def downloads_view():
    user_id = session["user_id"]
    report_type = request.args.get("type", "monthly").strip().lower()
    target_date = request.args.get("date", "").strip()
    target_month = request.args.get("month", "").strip()
    
    now = datetime.datetime.now()
    if not target_date:
        target_date = now.strftime("%Y-%m-%d")
    if not target_month:
        target_month = now.strftime("%Y-%m")
        
    target_val = target_date if report_type == "daily" else target_month
    report_data = compute_report_data(user_id, report_type, target_val)
    
    has_data = report_data["num_transactions"] > 0
    
    if report_type == "daily":
        try:
            d_parsed = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            report_title = d_parsed.strftime("%d %b %Y")
        except ValueError:
            report_title = target_date
    else:
        try:
            d_parsed = datetime.datetime.strptime(target_month, "%Y-%m")
            report_title = d_parsed.strftime("%B %Y")
        except ValueError:
            report_title = target_month

    currency_code, currency_symbol = get_currency_info(user_id)
    
    connection = get_db_connection()
    cursor = connection.cursor()
    current_month_str = now.strftime("%Y-%m")
    cursor.execute("SELECT SUM(amount) AS total FROM expenses WHERE user_id = %s AND substr(date, 1, 7) = %s", (user_id, current_month_str))
    monthly_expenses = cursor.fetchone()[0] or 0
    connection.close()

    budget_limit = float(get_setting(user_id, "monthly_budget", "10000.00"))
    budget_percent = min(100, int((monthly_expenses / budget_limit) * 100)) if budget_limit > 0 else 0

    return render_template(
        "downloads.html",
        report_type=report_type,
        target_date=target_date,
        target_month=target_month,
        report_data=report_data,
        has_data=has_data,
        report_title=report_title,
        monthly_expenses=monthly_expenses,
        budget_limit=budget_limit,
        budget_percent=budget_percent,
        currency_symbol=currency_symbol
    )


@app.route("/downloads/csv")
@login_required
def downloads_csv():
    user_id = session["user_id"]
    report_type = request.args.get("type", "monthly").strip().lower()
    target_date = request.args.get("date", "").strip()
    target_month = request.args.get("month", "").strip()
    
    now = datetime.datetime.now()
    if not target_date:
        target_date = now.strftime("%Y-%m-%d")
    if not target_month:
        target_month = now.strftime("%Y-%m")
        
    target_val = target_date if report_type == "daily" else target_month
    report_data = compute_report_data(user_id, report_type, target_val)
    
    if report_data["num_transactions"] == 0:
        return "No data available for this period.", 400
        
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Date", "Category", "Description", "Payment Method", "Amount"])
    for expense in report_data["expenses"]:
        cw.writerow([
            expense["date"],
            expense["category"],
            expense["description"] or "",
            expense["payment_method"],
            f"{float(expense['amount']):.2f}"
        ])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{report_type}_{target_val}.csv"
    output.headers["Content-type"] = "text/csv"
    return output


class ExpenseReportPDF(FPDF):
    def __init__(self, currency_symbol="Rs", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.currency_symbol = currency_symbol

    def header(self):
        self.set_fill_color(12, 17, 15)
        self.rect(0, 0, 210, 32, 'F')
        
        self.set_text_color(53, 196, 119)
        self.set_font("helvetica", "B", 18)
        self.set_xy(15, 8)
        self.cell(0, 8, "EXPENSE MANAGER", align="L")
        
        self.set_text_color(160, 170, 165)
        self.set_font("helvetica", "I", 9)
        self.set_xy(15, 16)
        self.cell(0, 6, "Expense Reports Log Summary", align="L")

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(127, 137, 133)
        self.cell(0, 10, f"Page {self.page_no()} | Generated by Expense Manager", align="C")


@app.route("/downloads/pdf")
@login_required
def downloads_pdf():
    user_id = session["user_id"]
    report_type = request.args.get("type", "monthly").strip().lower()
    target_date = request.args.get("date", "").strip()
    target_month = request.args.get("month", "").strip()
    
    now = datetime.datetime.now()
    if not target_date:
        target_date = now.strftime("%Y-%m-%d")
    if not target_month:
        target_month = now.strftime("%Y-%m")
        
    target_val = target_date if report_type == "daily" else target_month
    report_data = compute_report_data(user_id, report_type, target_val)
    
    if report_data["num_transactions"] == 0:
        return "No data available for this period.", 400
        
    _, currency_symbol = get_currency_info(user_id)
    
    if report_type == "daily":
        try:
            d_parsed = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            report_title = d_parsed.strftime("%d %b %Y")
        except ValueError:
            report_title = target_date
        report_label = f"Daily Expense Report - {report_title}"
    else:
        try:
            d_parsed = datetime.datetime.strptime(target_month, "%Y-%m")
            report_title = d_parsed.strftime("%B %Y")
        except ValueError:
            report_title = target_month
        report_label = f"Monthly Expense Report - {report_title}"

    pdf = ExpenseReportPDF(currency_symbol=currency_symbol)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=15)
    
    pdf.set_y(42)
    pdf.set_font("helvetica", "B", 15)
    pdf.set_text_color(30, 35, 33)
    pdf.cell(0, 8, report_label, ln=True, align="L")
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(100, 105, 103)
    pdf.cell(0, 5, f"Report Date: {now.strftime('%d %b %Y %H:%M')} | Currency: {currency_symbol}", ln=True, align="L")
    pdf.ln(5)
    
    pdf.set_fill_color(245, 247, 246)
    pdf.set_draw_color(210, 215, 212)
    pdf.set_text_color(30, 35, 33)
    pdf.set_font("helvetica", "B", 10)
    
    if report_type == "daily":
        pdf.cell(88, 14, f"Total Spent: {currency_symbol}{float(report_data['total_spent']):.2f}", border=1, fill=True, align="C")
        pdf.cell(4, 14, "")
        pdf.cell(88, 14, f"Transactions: {report_data['num_transactions']}", border=1, fill=True, align="C")
        pdf.ln(18)
    else:
        pdf.cell(42, 14, f"Spent: {currency_symbol}{float(report_data['total_spent']):.0f}", border=1, fill=True, align="C")
        pdf.cell(4, 14, "")
        pdf.cell(42, 14, f"Txns: {report_data['num_transactions']}", border=1, fill=True, align="C")
        pdf.cell(4, 14, "")
        pdf.cell(42, 14, f"Avg Daily: {currency_symbol}{float(report_data['avg_daily_spend']):.2f}", border=1, fill=True, align="C")
        pdf.cell(4, 14, "")
        pdf.cell(42, 14, f"Max Day: {currency_symbol}{float(report_data['highest_spending_day']):.0f}", border=1, fill=True, align="C")
        pdf.ln(18)

    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(30, 35, 33)
    pdf.cell(0, 8, "Category Breakdown Summary", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(80, 85, 83)
    
    for row in report_data["category_breakdown"]:
        pdf.cell(100, 7, f" {row['category']}", border="B")
        pdf.cell(80, 7, f"{currency_symbol}{float(row['total']):.2f} ", border="B", align="R", ln=True)
    pdf.ln(8)
    
    if report_type == "monthly":
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(30, 35, 33)
        pdf.cell(0, 8, "Day-by-Day Spending Summary", ln=True)
        pdf.set_font("helvetica", "", 8)
        pdf.set_text_color(80, 85, 83)
        
        col_width = 44
        col_count = 0
        for item in report_data["day_by_day"]:
            pdf.cell(col_width, 6, f"{item['day_label']}: {currency_symbol}{float(item['amount']):.0f}", border=1, align="C")
            col_count += 1
            if col_count == 4:
                pdf.ln(6)
                col_count = 0
        if col_count > 0:
            pdf.ln(10)
        else:
            pdf.ln(4)
            
    pdf.set_font("helvetica", "B", 12)
    pdf.set_text_color(30, 35, 33)
    pdf.cell(0, 8, "Detailed Expense Log List", ln=True)
    
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(225, 230, 227)
    pdf.cell(25, 8, " Date", border=1, fill=True)
    pdf.cell(35, 8, " Category", border=1, fill=True)
    pdf.cell(65, 8, " Description", border=1, fill=True)
    pdf.cell(30, 8, " Payment Method", border=1, fill=True)
    pdf.cell(25, 8, " Amount ", border=1, fill=True, align="R", ln=True)
    
    pdf.set_font("helvetica", "", 8)
    for exp in report_data["expenses"]:
        pdf.cell(25, 7, f" {exp['date']}", border=1)
        pdf.cell(35, 7, f" {exp['category']}", border=1)
        pdf.cell(65, 7, f" {exp['description'] or ''}", border=1)
        pdf.cell(30, 7, f" {exp['payment_method']}", border=1)
        pdf.cell(25, 7, f"{currency_symbol}{float(exp['amount']):.2f} ", border=1, align="R", ln=True)
        
    pdf_bytes = pdf.output()
    response = make_response(pdf_bytes)
    response.headers["Content-Disposition"] = f"attachment; filename=report_{report_type}_{target_val}.pdf"
    response.headers["Content-Type"] = "application/pdf"
    return response


init_db()

if __name__ == "__main__":
    app.run(debug=True)