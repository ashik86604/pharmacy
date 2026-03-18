from pprint import pp
from flask import request
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from functools import wraps
from db import get_db_connection
from config import Config
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
app = Flask(__name__)
app.config.from_object(Config)
from openai import OpenAI
from flask import jsonify
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)

@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def get_user_role():
    if session.get("role") == "super_admin":
        return "super_admin"
    elif session.get("admin"):
        return "admin"
    return None

@app.route("/chatbot")
def chatbot():

    role = get_user_role()

    if role not in ["admin", "super_admin"]:
        return redirect(url_for("login"))

    return render_template("chatbot.html")

@app.route("/chat_api", methods=["POST"])
def chat_api():

    user_message = request.json.get("message")

    completion = client.chat.completions.create(
        model="institute-of-science-tokyo/llama-3.1-swallow-8b-instruct-v0.1",
        messages=[
            {
                "role": "system",
                "content": "You are a pharmacy assistant. Explain medicine uses, dosage and side effects."
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        temperature=0.5,
        max_tokens=500
    )

    bot_reply = completion.choices[0].message.content

    # Token usage info
    prompt_tokens = completion.usage.prompt_tokens
    completion_tokens = completion.usage.completion_tokens
    total_tokens = completion.usage.total_tokens

    # Save chat
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO chat_history (user_message, bot_reply)
        VALUES (%s,%s)
    """, (user_message, bot_reply))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "reply": bot_reply,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens
    })

# @app.route("/chat_api", methods=["POST"])
# def chat_api():

#     user_message = request.json.get("message")

#     completion = client.chat.completions.create(
#         model="institute-of-science-tokyo/llama-3.1-swallow-8b-instruct-v0.1",
#         messages=[
#             {
#                 "role": "system",
#                 "content": "You are a pharmacy assistant. Explain tablet uses, dosage, side effects, and precautions clearly."
#             },
#             {
#                 "role": "user",
#                 "content": user_message
#             }
#         ],
#         temperature=0.5,
#         max_tokens=500
#     )

#     bot_reply = completion.choices[0].message.content

#     # Save chat in DB
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     cursor.execute("""
#         INSERT INTO chat_history (user_message, bot_reply)
#         VALUES (%s, %s)
#     """, (user_message, bot_reply))

#     conn.commit()
#     cursor.close()
#     conn.close()

#     return jsonify({"reply": bot_reply})



def send_invoice_email(to_email, bill, items):

    sender_email = "ashiks.shabbir@gmail.com"
    sender_password = "etje rlgg zmqx kiuz"

    subject = f"Invoice - Bill ID {bill['b_id']}"

    # Build invoice content
    body = f"""
    Pharmacy Invoice

    Bill ID: {bill['b_id']}
    Date: {bill['created_at']}
    Customer Phone: {bill['c_phone']}

    ----------------------------------

    """

    for item in items:
        total = item['price'] * item['quantity']
        body += f"{item['name']} - {item['quantity']} x {item['price']} = {total}\n"

    body += f"\nGrand Total: ₹ {bill['total_price']}\n"

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = to_email
    message["Subject"] = subject

    message.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(sender_email, sender_password)
    server.send_message(message)
    server.quit()

    
# ==============================
# LOGIN REQUIRED DECORATOR
# ==============================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin' not in session:
            flash("Please login first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# ==============================
# LOGIN ROUTE
# ==============================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        admin_name = request.form.get("admin_name")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM admins WHERE admin_name = %s",
            (admin_name,)
        )
        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        # Check hashed password
        if admin and check_password_hash(admin["password"], password):
            session['admin'] = admin['admin_name']
            flash("Login Successful!", "success")
            return redirect(url_for('dashboard'))  # PRG Pattern
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")

@app.route("/alert_center")
def alert_center():

    if session.get("role") != "super_admin":
        return redirect(url_for("super_login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Out of stock
    cursor.execute("SELECT * FROM stock WHERE stockno = 0")
    out_of_stock = cursor.fetchall()

    # Low stock
    cursor.execute("SELECT * FROM stock WHERE stockno < 5 AND stockno > 0")
    low_stock = cursor.fetchall()

    # Expiring in 30 days
    cursor.execute("""
        SELECT * FROM stock
        WHERE expiry_date IS NOT NULL
        AND expiry_date BETWEEN CURDATE()
        AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
    """)
    expiring_soon = cursor.fetchall()

    # Already expired
    cursor.execute("""
        SELECT * FROM stock
        WHERE expiry_date IS NOT NULL
        AND expiry_date < CURDATE()
    """)
    expired = cursor.fetchall()

    # Top selling
    cursor.execute("""
        SELECT s.name, SUM(ri.quantity) AS total_sold
        FROM record_items ri
        JOIN stock s ON ri.t_id = s.t_id
        GROUP BY ri.t_id
        ORDER BY total_sold DESC
        LIMIT 1
    """)
    top_selling = cursor.fetchone()

    # Least selling
    cursor.execute("""
        SELECT s.name, SUM(ri.quantity) AS total_sold
        FROM record_items ri
        JOIN stock s ON ri.t_id = s.t_id
        GROUP BY ri.t_id
        ORDER BY total_sold ASC
        LIMIT 1
    """)
    least_selling = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "alert_center.html",
        out_of_stock=out_of_stock,
        low_stock=low_stock,
        expiring_soon=expiring_soon,
        expired=expired,
        top_selling=top_selling,
        least_selling=least_selling
    )

from flask import request, send_file
import openpyxl
from openpyxl import Workbook
from io import BytesIO


@app.route("/daily_report", methods=["GET", "POST"])
def daily_report():

    if session.get("role") != "super_admin":
        return redirect(url_for("super_login"))

    selected_date = request.form.get("date")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if selected_date:
        cursor.execute("""
            SELECT * FROM records
            WHERE DATE(created_at) = %s
        """, (selected_date,))
    else:
        cursor.execute("""
            SELECT * FROM records
            WHERE DATE(created_at) = CURDATE()
        """)

    records = cursor.fetchall()

    total = sum(record["total_price"] for record in records)

    cursor.close()
    conn.close()

    return render_template(
        "daily_report.html",
        records=records,
        total=total,
        selected_date=selected_date
    )

@app.route("/export_excel")
def export_excel():

    if session.get("role") != "super_admin":
        return redirect(url_for("super_login"))

    selected_date = request.args.get("date")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if selected_date:
        cursor.execute("""
            SELECT * FROM records
            WHERE DATE(created_at) = %s
        """, (selected_date,))
    else:
        cursor.execute("""
            SELECT * FROM records
            WHERE DATE(created_at) = CURDATE()
        """)

    records = cursor.fetchall()

    cursor.close()
    conn.close()

    # Create Excel file
    wb = Workbook()
    ws = wb.active
    ws.title = "Daily Report"

    ws.append(["Bill ID", "Customer Phone", "Total Price", "Date"])

    for record in records:
        ws.append([
            record["b_id"],
            record["c_phone"],
            record["total_price"],
            str(record["created_at"])
        ])

    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        download_name="daily_sales_report.xlsx",
        as_attachment=True
    )

@app.route("/super_login", methods=["GET", "POST"])
def super_login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM super_admin WHERE username=%s",
            (username,)
        )
        super_admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if super_admin and check_password_hash(super_admin["password"], password):
            session["role"] = "super_admin"
            session["super_name"] = username
            return redirect(url_for("super_dashboard"))
        else:
            flash("Invalid Super Admin credentials", "danger")

    return render_template("super_login.html")

@app.route("/super_dashboard")
def super_dashboard():

    if session.get("role") != "super_admin":
        return redirect(url_for("super_login"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1️⃣ Total Revenue
    cursor.execute("SELECT SUM(total_price) AS total FROM records")
    revenue_row = cursor.fetchone()
    total_revenue = revenue_row["total"] if revenue_row["total"] else 0

    # 2️⃣ Total Admins
    cursor.execute("SELECT COUNT(*) AS count FROM admins")
    total_admins = cursor.fetchone()["count"]

    # 3️⃣ Total Bills
    cursor.execute("SELECT COUNT(*) AS count FROM records")
    total_bills = cursor.fetchone()["count"]

    # 4️⃣ Low Stock (less than 5)
    cursor.execute("SELECT COUNT(*) AS count FROM stock WHERE stockno < 5")
    low_stock_count = cursor.fetchone()["count"]

    # 5️⃣ Expiring Soon (next 30 days)
    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM stock
        WHERE expiry_date IS NOT NULL
        AND expiry_date BETWEEN CURDATE()
        AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
    """)
    expiring_count = cursor.fetchone()["count"]

    # 6️⃣ Top Selling Medicine
    cursor.execute("""
        SELECT s.name, SUM(ri.quantity) AS total_sold
        FROM record_items ri
        JOIN stock s ON ri.t_id = s.t_id
        GROUP BY ri.t_id
        ORDER BY total_sold DESC
        LIMIT 1
    """)
    top_medicine = cursor.fetchone()

    if not top_medicine:
        top_medicine = {"name": "N/A", "total_sold": 0}

    # 7️⃣ Real Profit (if cost_price column exists)
    try:
        cursor.execute("""
            SELECT SUM((s.price - s.cost_price) * ri.quantity) AS profit
            FROM record_items ri
            JOIN stock s ON ri.t_id = s.t_id
        """)
        profit_row = cursor.fetchone()
        total_profit = profit_row["profit"] if profit_row["profit"] else 0
    except:
        total_profit = 0

    cursor.close()
    conn.close()

    return render_template(
        "super_dashboard.html",
        total_revenue=total_revenue,
        total_admins=total_admins,
        total_bills=total_bills,
        low_stock_count=low_stock_count,
        expiring_count=expiring_count,
        top_medicine=top_medicine,
        total_profit=total_profit
    )

from werkzeug.security import generate_password_hash

@app.route("/add_admin", methods=["GET", "POST"])
def add_admin():

    if session.get("role") != "super_admin":
        return redirect(url_for("super_login"))

    if request.method == "POST":

        name = request.form.get("admin_name")
        password = request.form.get("password")

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO admins (admin_name, password)
            VALUES (%s,%s)
        """, (name, hashed_password))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Admin added successfully!", "success")
        return redirect(url_for("super_dashboard"))

    return render_template("add_admin.html")

@app.route("/manage_admins")
def manage_admins():

    if session.get("role") != "super_admin":
        return redirect(url_for("home"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM admins")
    admins = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("manage_admins.html", admins=admins)

@app.route("/delete_admin/<int:a_id>")
def delete_admin(a_id):

    if session.get("role") != "super_admin":
        return redirect(url_for("home"))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM admins WHERE a_id=%s", (a_id,))
    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for("manage_admins"))

@app.route("/alerts")
def alerts():

    if session.get("role") not in ["admin", "super_admin"]:
        return redirect(url_for("home"))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Low stock
    cursor.execute("SELECT * FROM stock WHERE stockno < 5")
    low_stock = cursor.fetchall()

    # Expiring soon (next 30 days)
    cursor.execute("""
        SELECT * FROM stock
        WHERE expiry_date IS NOT NULL
        AND expiry_date BETWEEN CURDATE()
        AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)
    """)
    expiring = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("alerts.html",
                           low_stock=low_stock,
                           expiring=expiring)
# ==============================
# DASHBOARD (Protected)
# ==============================
@app.route("/dashboard")
@login_required
def dashboard():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Total Medicines
    cursor.execute("SELECT COUNT(*) AS total FROM stock")
    total_medicines = cursor.fetchone()['total']

    # Total Bills
    cursor.execute("SELECT COUNT(*) AS total FROM records")
    total_bills = cursor.fetchone()['total']

    # Total Sales
    cursor.execute("SELECT SUM(total_price) AS total FROM records")
    total_sales = cursor.fetchone()['total']
    if total_sales is None:
        total_sales = 0

    cursor.close()
    conn.close()

    return render_template("dashboard.html",
                           total_medicines=total_medicines,
                           total_bills=total_bills,
                           total_sales=total_sales)


# ==============================
# VIEW STOCK
# ==============================
@app.route("/stock")
@login_required
def stock():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM stock ORDER BY t_id DESC")
    medicines = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("stock.html", medicines=medicines)


# ==============================
# ADD STOCK
# ==============================
@app.route("/add_stock", methods=["GET", "POST"])
@login_required
def add_stock():

    if request.method == "POST":

        name = request.form.get("name")
        stockno = request.form.get("stockno")
        price = request.form.get("price")

        # Basic Validation
        if not name or not stockno or not price:
            flash("All fields are required", "danger")
            return redirect(url_for("add_stock"))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO stock (name, stockno, price) VALUES (%s,%s,%s)",
            (name, stockno, price)
        )

        conn.commit()
        cursor.close()
        conn.close()

        flash("Medicine added successfully", "success")
        return redirect(url_for("stock"))

    return render_template("add_stock.html")


# @app.route("/email_invoice/<int:bill_id>")
# @login_required
# def email_invoice(bill_id):

#     conn = get_db_connection()
#     cursor = conn.cursor(dictionary=True)

#     # Get bill
#     cursor.execute("SELECT * FROM records WHERE b_id=%s", (bill_id,))
#     bill = cursor.fetchone()

#     # Get items
#     cursor.execute("""
#         SELECT s.name, s.price, ri.quantity
#         FROM record_items ri
#         JOIN stock s ON ri.t_id = s.t_id
#         WHERE ri.b_id=%s
#     """, (bill_id,))
#     items = cursor.fetchall()

#     # Get customer email
#     cursor.execute("SELECT gmail FROM customers WHERE phone=%s", (bill['c_phone'],))
#     customer = cursor.fetchone()

#     cursor.close()
#     conn.close()

#     if customer and customer['gmail']:
#         send_invoice_email(customer['gmail'], bill, items)
#         flash("Invoice emailed successfully!", "success")
#     else:
#         flash("Customer email not found!", "danger")

#     return redirect(url_for("invoice", bill_id=bill_id))
@app.route("/email_invoice/<int:bill_id>", methods=["POST"])
@login_required
def email_invoice(bill_id):

    to_email = request.form.get("email")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get bill
    cursor.execute("SELECT * FROM records WHERE b_id=%s", (bill_id,))
    bill = cursor.fetchone()

    # Get items
    cursor.execute("""
        SELECT s.name, s.price, ri.quantity
        FROM record_items ri
        JOIN stock s ON ri.t_id = s.t_id
        WHERE ri.b_id=%s
    """, (bill_id,))
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    try:
        send_invoice_email(to_email, bill, items)
        flash("Invoice emailed successfully!", "success")
    except Exception as e:
        flash("Email sending failed!", "danger")

    return redirect(url_for("invoice", bill_id=bill_id))
# ==============================
# DELETE STOCK
# ==============================
@app.route("/delete_stock/<int:id>")
@login_required
def delete_stock(id):

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM stock WHERE t_id=%s", (id,))
    conn.commit()

    cursor.close()
    conn.close()

    flash("Medicine deleted successfully", "warning")
    return redirect(url_for("stock"))

# ==============================
# BILLING SYSTEM
# ==============================
@app.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM stock WHERE stockno > 0")
    medicines = cursor.fetchall()
    for med in medicines:
        med['price'] = int(med['price'])
    if request.method == "POST":
        phone = request.form.get("phone")
        total_price = request.form.get("total_price")

        try:
            # conn.start_transaction()

            cursor.execute(
                "INSERT INTO records (c_phone, total_price) VALUES (%s,%s)",
                (phone, total_price)
            )
            bill_id = cursor.lastrowid

            medicine_ids = request.form.getlist("medicine_id")
            quantities = request.form.getlist("quantity")

            for med_id, qty in zip(medicine_ids, quantities):

                qty = int(qty)

                cursor.execute(
                    "SELECT stockno FROM stock WHERE t_id=%s",
                    (med_id,)
                )
                stock_data = cursor.fetchone()

                if not stock_data or stock_data['stockno'] < qty:
                    raise Exception("Insufficient stock!")

                cursor.execute(
                    "INSERT INTO record_items (b_id, t_id, quantity) VALUES (%s,%s,%s)",
                    (bill_id, med_id, qty)
                )

                cursor.execute(
                    "UPDATE stock SET stockno = stockno - %s WHERE t_id=%s",
                    (qty, med_id)
                )

            conn.commit()

            flash("Bill generated successfully!", "success")
            return redirect(url_for("invoice", bill_id=bill_id))

        except Exception as e:
            conn.rollback()
            flash(str(e), "danger")

        finally:
            cursor.close()
            conn.close()

    cursor.close()
    conn.close()
    return render_template("billing.html", medicines=medicines)

# ==============================
# INVOICE PAGE
# ==============================
@app.route("/invoice/<int:bill_id>")
@login_required
def invoice(bill_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM records WHERE b_id=%s", (bill_id,))
    bill = cursor.fetchone()

    cursor.execute("""
        SELECT s.name, s.price, r.quantity
        FROM record_items r
        JOIN stock s ON r.t_id = s.t_id
        WHERE r.b_id=%s
    """, (bill_id,))
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("invoice.html", bill=bill, items=items)

# ==============================
# RECORDS PAGE
# ==============================
@app.route("/records")
@login_required
def records():

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Optional date filtering
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    phone = request.args.get("phone")

    if start_date and end_date:
        cursor.execute("""
            SELECT * FROM records
            WHERE DATE(created_at) BETWEEN %s AND %s
            ORDER BY b_id DESC
        """, (start_date, end_date))
    elif phone:
        cursor.execute("""
            SELECT * FROM records
            WHERE c_phone = %s
            ORDER BY b_id DESC
        """, (phone,))
    else:
        cursor.execute("""
            SELECT * FROM records
            ORDER BY b_id DESC
        """)

    bills = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("records.html", bills=bills)
# ==============================
# VIEW SINGLE RECORD
# ==============================
@app.route("/record/<int:bill_id>")
@login_required
def view_record(bill_id):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM records WHERE b_id=%s", (bill_id,))
    bill = cursor.fetchone()

    cursor.execute("""
        SELECT s.name, s.price, r.quantity
        FROM record_items r
        JOIN stock s ON r.t_id = s.t_id
        WHERE r.b_id=%s
    """, (bill_id,))
    items = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("view_record.html", bill=bill, items=items)
# ==============================
# LOGOUT
# ==============================
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)