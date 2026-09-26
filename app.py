from flask import Flask, render_template, request, send_file, session, redirect
import sqlite3
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ganti-ini-nanti")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ganti-password-ini")

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated
def create_invoice(order_number, name, email, address, package, price):

    os.makedirs("invoices", exist_ok=True)

    filename = f"invoices/{order_number}.pdf"

    pdf = canvas.Canvas(filename, pagesize=A4)

    width, height = A4
    

    # Header
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(50, height - 60, "KE-MIPHAN RESEARCH")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 78, "Thailand")

    # Invoice title
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(50, height - 125, "INVOICE")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 145, f"Order #{order_number}")

    # Customer
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, height - 190, "BILL TO")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 208, name)
    pdf.drawString(50, height - 224, email)
    pdf.drawString(50, height - 240, address)

    # Order details
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, height - 285, "ORDER DETAILS")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 305, "Package")
    pdf.drawString(300, height - 305, "Price")

    pdf.line(50, height - 315, 545, height - 315)

    pdf.drawString(50, height - 335, package)
    pdf.drawString(300, height - 335, price)

    pdf.line(50, height - 350, 545, height - 350)

    # Total
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(300, height - 380, f"TOTAL: {price}")

    # Payment
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, height - 430, "PAYMENT")

    # Payment
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, height - 430, "PAYMENT")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 450, "Bitcoin (BTC)")

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(50, height - 470, "Wallet Address")

    pdf.setFont("Helvetica", 8)
    pdf.drawString(
        50,
        height - 488,
        "bc1qx8s2ch385tn3fm05elan67ahy0exj2t5z4y27p"
    )

    pdf.setFont("Helvetica", 10)
    pdf.drawString(
        50,
        height - 515,
        "Payment Status: PENDING PAYMENT"
    )

    pdf.save()

    return filename
def init_db():
    conn = sqlite3.connect("shop.db")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT,
            name TEXT,
            email TEXT,
            address TEXT,
            package TEXT,
            price TEXT,
            status TEXT
        )
    """)

    conn.commit()
    conn.close()

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/checkout")
def checkout():
    package = request.args.get("package")
    price = request.args.get("price")

    return render_template(
        "checkout.html",
        package=package,
        price=price
    )


@app.route("/place-order", methods=["POST"])
def place_order():

    from datetime import datetime

    name = request.form.get("name")
    email = request.form.get("email")
    address = request.form.get("address")
    package = request.form.get("package")
    price = request.form.get("price")

    # Membuat nomor order otomatis
    order_number = "SN-" + datetime.now().strftime("%Y%m%d-%H%M%S")

    conn = sqlite3.connect("shop.db")

    conn.execute("""
        INSERT INTO orders (
            order_number,
            name,
            email,
            address,
            package,
            price,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        order_number,
        name,
        email,
        address,
        package,
        price,
        "Pending Payment"
    ))

    conn.commit()
    conn.close()
    invoice_file = create_invoice(
        order_number,
        name,
        email,
        address,
        package,
        price
    )
    return render_template(
        "success.html",
        name=name,
        email=email,
        address=address,
        package=package,
        price=price,
        order_number=order_number
    )
@app.route("/invoice/<order_number>")
def view_invoice(order_number):

    filename = f"invoices/{order_number}.pdf"

    if not os.path.exists(filename):
        return "Invoice not found", 404

    return send_file(
        filename,
        mimetype="application/pdf",
        as_attachment=False
    )
@app.route("/payment-proof/<order_number>")
def view_payment_proof(order_number):

    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row

    order = conn.execute("""
        SELECT payment_proof
        FROM orders
        WHERE order_number = ?
    """, (order_number,)).fetchone()

    conn.close()

    if not order or not order["payment_proof"]:
        return "Payment proof not found", 404

    filepath = order["payment_proof"]

    if not os.path.exists(filepath):
        return "Payment proof file not found", 404

    return send_file(filepath)
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect("/admin/orders")
        return "Password salah", 401
    return '''
        <form method="post" style="max-width:300px;margin:100px auto;font-family:sans-serif">
            <h3>Admin Login</h3>
            <input type="password" name="password" placeholder="Password"
                   style="width:100%;padding:8px;margin-bottom:10px">
            <button type="submit" style="width:100%;padding:8px">Login</button>
        </form>
    '''

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect("/admin/login")
@app.route("/admin/orders")
@login_required
def admin_orders():

    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row

    orders = conn.execute("""
        SELECT * FROM orders
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin_orders.html",
        orders=orders
    )
@app.route("/refund")
def refund():
    return render_template("refund.html")
@app.route("/payment")
def payment():
    return render_template("payment.html")
@app.route("/payment-proof", methods=["GET", "POST"])
def payment_proof():

    if request.method == "POST":
        order_number = request.form.get("order_number")
        file = request.files.get("payment_proof")

        if not order_number or not file:
            return "Order number and payment proof are required", 400

        filename = file.filename

        if not filename:
            return "Invalid file", 400

        payment_folder = "payment_proofs"
        os.makedirs(payment_folder, exist_ok=True)

        filepath = os.path.join(
            payment_folder,
            f"{order_number}_{filename}"
        )

        file.save(filepath)

        conn = sqlite3.connect("shop.db")

        conn.execute("""
            UPDATE orders
            SET payment_proof = ?,
                status = ?
            WHERE order_number = ?
            """, (
            filepath,
            "Payment Verification",
            order_number
        ))

        conn.commit()
        conn.close()

        return "Payment proof submitted successfully"

    return render_template("payment_proof.html")
@app.route("/track-order")
def track_order():

    order_number = request.args.get("order_number")

    order = None

    if order_number:

        conn = sqlite3.connect("shop.db")
        conn.row_factory = sqlite3.Row

        order = conn.execute("""
            SELECT *
            FROM orders
            WHERE order_number = ?
        """, (order_number,)).fetchone()

        conn.close()

    return render_template(
        "track_order.html",
        order=order
    )
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
