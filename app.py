import os
import io
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, send_file
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


# ==========================================
# DATABASE: SUPABASE POSTGRESQL
# ==========================================

def get_db():
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL belum diatur di Vercel Environment Variables."
        )

    return psycopg2.connect(
        database_url,
        sslmode="require",
        connect_timeout=10
    )


def init_db():
    conn = get_db()

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS orders (
                        id BIGSERIAL PRIMARY KEY,
                        order_number TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        email TEXT NOT NULL,
                        address TEXT NOT NULL,
                        package TEXT NOT NULL,
                        price TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'Pending Payment',
                        payment_proof BYTEA,
                        payment_proof_name TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                # Menambahkan kolom untuk tabel versi lama.
                cur.execute("""
                    ALTER TABLE orders
                    ADD COLUMN IF NOT EXISTS payment_proof BYTEA
                """)

                cur.execute("""
                    ALTER TABLE orders
                    ADD COLUMN IF NOT EXISTS payment_proof_name TEXT
                """)

                cur.execute("""
                    ALTER TABLE orders
                    ADD COLUMN IF NOT EXISTS created_at
                    TIMESTAMPTZ DEFAULT NOW()
                """)

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    orders_order_number_idx
                    ON orders(order_number)
                """)
    finally:
        conn.close()


# ==========================================
# INVOICE PDF
# ==========================================

def create_invoice(
    order_number, name, email, address,
    package, price, status="Pending Payment"
):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    def line(y, text, font="Helvetica", size=10):
        pdf.setFont(font, size)
        pdf.drawString(
            50, y,
            str(text or "").replace("\n", " ")[:90]
        )

    line(height - 60, "KE-MIPHAN RESEARCH",
         "Helvetica-Bold", 20)
    line(height - 78, "Thailand")
    line(height - 125, "INVOICE", "Helvetica-Bold", 18)
    line(height - 145, f"Order #{order_number}")

    line(height - 190, "BILL TO", "Helvetica-Bold", 11)
    line(height - 208, name)
    line(height - 224, email)
    line(height - 240, address)

    line(height - 285, "ORDER DETAILS", "Helvetica-Bold", 11)
    line(height - 305, "Package")
    line(height - 305, "Price")
    pdf.line(50, height - 315, 545, height - 315)

    line(height - 335, package)
    line(height - 335, price)
    pdf.line(50, height - 350, 545, height - 350)

    line(height - 380, f"TOTAL: {price}",
         "Helvetica-Bold", 12)

    line(height - 430, "PAYMENT", "Helvetica-Bold", 11)
    line(height - 450, "Bitcoin (BTC)")
    line(height - 470, "Wallet Address",
         "Helvetica-Bold", 9)
    line(
        height - 488,
        "bc1qx8s2ch385tn3fm05elan67ahy0exj2t5z4y27p",
        size=8
    )
    line(height - 515, f"Payment Status: {status}")

    pdf.save()
    buffer.seek(0)
    return buffer


# ==========================================
# HOME & CHECKOUT
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/checkout")
def checkout():
    package = request.args.get("package", "")
    price = request.args.get("price", "")

    return render_template(
        "checkout.html",
        package=package,
        price=price
    )


# ==========================================
# CREATE ORDER
# ==========================================

@app.route("/place-order", methods=["POST"])
def place_order():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    address = (request.form.get("address") or "").strip()
    package = (request.form.get("package") or "").strip()
    price = (request.form.get("price") or "").strip()

    if not all([name, email, address, package, price]):
        return "Semua data pesanan wajib diisi.", 400

    order_number = (
        "SN-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )

    try:
        init_db()
        conn = get_db()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO orders (
                            order_number, name, email,
                            address, package, price, status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        order_number,
                        name,
                        email,
                        address,
                        package,
                        price,
                        "Pending Payment"
                    ))
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal menyimpan order")
        return "Pesanan gagal disimpan. Silakan coba lagi.", 500

    return render_template(
        "success.html",
        name=name,
        email=email,
        address=address,
        package=package,
        price=price,
        order_number=order_number
    )


# ==========================================
# VIEW / DOWNLOAD INVOICE
# ==========================================

@app.route("/invoice/<order_number>")
def view_invoice(order_number):
    try:
        init_db()
        conn = get_db()

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT order_number, name, email,
                           address, package, price, status
                    FROM orders
                    WHERE order_number = %s
                """, (order_number,))
                order = cur.fetchone()
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal mengambil invoice")
        return "Layanan invoice sedang bermasalah.", 500

    if not order:
        return "Invoice tidak ditemukan.", 404

    pdf_file = create_invoice(
        order["order_number"],
        order["name"],
        order["email"],
        order["address"],
        order["package"],
        order["price"],
        order["status"]
    )

    return send_file(
        pdf_file,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"{order_number}.pdf"
    )


# ==========================================
# UPLOAD PAYMENT PROOF
# ==========================================

@app.route("/payment-proof", methods=["GET", "POST"])
def payment_proof():
    if request.method == "GET":
        return render_template("payment_proof.html")

    order_number = (
        request.form.get("order_number") or ""
    ).strip()

    uploaded = request.files.get("payment_proof")

    if not order_number or not uploaded:
        return "Nomor order dan bukti pembayaran wajib diisi.", 400

    if not uploaded.filename:
        return "File tidak valid.", 400

    filename = secure_filename(uploaded.filename)

    if not filename:
        return "Nama file tidak valid.", 400

    file_bytes = uploaded.read()

    if not file_bytes:
        return "File kosong.", 400

    if len(file_bytes) > 8 * 1024 * 1024:
        return "Ukuran file maksimal 8 MB.", 413

    try:
        init_db()
        conn = get_db()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE orders
                        SET payment_proof = %s,
                            payment_proof_name = %s,
                            status = %s
                        WHERE order_number = %s
                    """, (
                        psycopg2.Binary(file_bytes),
                        filename,
                        "Payment Verification",
                        order_number
                    ))

                    if cur.rowcount == 0:
                        return "Nomor order tidak ditemukan.", 404
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal menyimpan bukti pembayaran")
        return "Bukti pembayaran gagal disimpan.", 500

    return "Bukti pembayaran berhasil dikirim."


# ==========================================
# VIEW PAYMENT PROOF
# ==========================================

@app.route("/payment-proof/<order_number>")
def view_payment_proof(order_number):
    try:
        init_db()
        conn = get_db()

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT payment_proof, payment_proof_name
                    FROM orders
                    WHERE order_number = %s
                """, (order_number,))
                order = cur.fetchone()
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal mengambil bukti pembayaran")
        return "Layanan bukti pembayaran sedang bermasalah.", 500

    if not order or not order["payment_proof"]:
        return "Bukti pembayaran tidak ditemukan.", 404

    return send_file(
        io.BytesIO(bytes(order["payment_proof"])),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=secure_filename(
            order["payment_proof_name"] or "payment-proof"
        )
    )


# ==========================================
# ADMIN ORDERS
# ==========================================

@app.route("/admin/orders")
def admin_orders():
    # Tambahkan autentikasi admin sebelum situs digunakan publik.
    try:
        init_db()
        conn = get_db()

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM orders
                    ORDER BY id DESC
                """)
                orders = cur.fetchall()
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal mengambil daftar order")
        return "Daftar pesanan sedang bermasalah.", 500

    return render_template(
        "admin_orders.html",
        orders=orders
    )


# ==========================================
# OTHER PAGES
# ==========================================

@app.route("/refund")
def refund():
    return render_template("refund.html")


@app.route("/payment")
def payment():
    return render_template("payment.html")


@app.route("/track-order")
def track_order():
    order_number = (
        request.args.get("order_number") or ""
    ).strip()

    order = None

    if order_number:
        try:
            init_db()
            conn = get_db()

            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT * FROM orders
                        WHERE order_number = %s
                    """, (order_number,))
                    order = cur.fetchone()
            finally:
                conn.close()

        except Exception:
            app.logger.exception("Gagal melacak order")
            return "Pelacakan pesanan sedang bermasalah.", 500

    return render_template(
        "track_order.html",
        order=order
    )


# ==========================================
# HEALTH CHECK
# ==========================================

@app.route("/health")
def health():
    try:
        conn = get_db()
        conn.close()

        return {
            "status": "ok",
            "database": "connected"
        }, 200

    except Exception:
        app.logger.exception("Health check gagal")

        return {
            "status": "error",
            "database": "unavailable"
        }, 503


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
