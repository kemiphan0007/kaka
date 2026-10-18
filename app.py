import os
import re
import uuid
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    flash,
    abort,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")

logging.basicConfig(level=logging.INFO)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        raise RuntimeError(
            "Environment variable DATABASE_URL belum diatur."
        )

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
        sslmode="require",
    )


def fetch_one(query, params=()):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()
    finally:
        conn.close()


def fetch_all(query, params=()):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def execute_query(query, params=()):
    conn = get_db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
    finally:
        conn.close()


def parse_price(value):
    """Mengubah '$4,650' menjadi Decimal('4650')."""
    cleaned = re.sub(r"[^0-9.]", "", str(value or ""))

    try:
        amount = Decimal(cleaned)
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
        return amount
    except (InvalidOperation, ValueError):
        raise ValueError("Harga tidak valid.")


# =========================================================
# HOME & CHECKOUT
# =========================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if request.method == "POST":
        return redirect(url_for("checkout"))

    return render_template("checkout.html")


# =========================================================
# PLACE ORDER
# =========================================================

@app.route("/place-order", methods=["POST"])
def place_order():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    address = (request.form.get("address") or "").strip()
    package = (request.form.get("package") or "").strip()
    price = (request.form.get("price") or "").strip()

    try:
        quantity = int(request.form.get("quantity") or "1")
        total_amount = parse_price(price)

        if quantity < 1:
            raise ValueError("Jumlah minimal satu.")

    except (ValueError, TypeError):
        return "Jumlah atau harga pesanan tidak valid.", 400

    if not all([name, email, address, package]):
        return "Nama, email, alamat, dan paket wajib diisi.", 400

    order_number = (
        "SN-"
        + datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )

    try:
        conn = get_db()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO public.orders (
                            order_number,
                            customer_name,
                            customer_email,
                            shipping_address,
                            product_name,
                            package_name,
                            quantity,
                            total_amount,
                            payment_status,
                            order_status,
                            name,
                            email,
                            address,
                            package,
                            price,
                            status
                        )
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            order_number,
                            name,
                            email,
                            address,
                            "SR17018 Powder Product",
                            package,
                            quantity,
                            total_amount,
                            "pending",
                            "order_placed",
                            name,
                            email,
                            address,
                            package,
                            price,
                            "Pending Payment",
                        ),
                    )
        finally:
            conn.close()

    except Exception:
        app.logger.exception(
            "Gagal menyimpan order %s", order_number
        )
        return (
            "Pesanan gagal disimpan. Silakan coba kembali.",
            500,
        )

    return render_template(
        "success.html",
        order_number=order_number,
        name=name,
        email=email,
        address=address,
        package=package,
        price=price,
        quantity=quantity,
    )


# =========================================================
# INVOICE
# =========================================================

@app.route("/invoice/<order_number>")
def invoice(order_number):
    try:
        order = fetch_one(
            """
            SELECT *
            FROM public.orders
            WHERE order_number = %s
            LIMIT 1
            """,
            (order_number,),
        )
    except Exception:
        app.logger.exception("Gagal mengambil invoice")
        return "Gagal mengambil data invoice.", 500

    if not order:
        abort(404)

    return render_template("invoice.html", order=order)


# =========================================================
# PAYMENT PAGE
# =========================================================

@app.route("/payment", methods=["GET", "POST"])
def payment():
    order_number = (
        request.values.get("order_number") or ""
    ).strip()

    if not order_number:
        return render_template("payment.html")

    try:
        order = fetch_one(
            """
            SELECT *
            FROM public.orders
            WHERE order_number = %s
            LIMIT 1
            """,
            (order_number,),
        )
    except Exception:
        app.logger.exception("Gagal mengambil data pembayaran")
        return "Gagal mengambil data pembayaran.", 500

    if not order:
        abort(404)

    return render_template("payment.html", order=order)


# =========================================================
# PAYMENT PROOF PAGE
# =========================================================

@app.route("/payment-proof/<order_number>", methods=["GET"])
def payment_proof_page(order_number):
    try:
        order = fetch_one(
            """
            SELECT *
            FROM public.orders
            WHERE order_number = %s
            LIMIT 1
            """,
            (order_number,),
        )
    except Exception:
        app.logger.exception("Gagal mengambil pesanan")
        return "Gagal mengambil pesanan.", 500

    if not order:
        abort(404)

    return render_template("payment_proof.html", order=order)


# =========================================================
# SUBMIT PAYMENT PROOF
# =========================================================

@app.route("/payment-proof", methods=["POST"])
def payment_proof():
    order_number = (
        request.form.get("order_number") or ""
    ).strip()

    uploaded_file = request.files.get("payment_proof")

    if not order_number or not uploaded_file:
        return "Nomor pesanan dan bukti pembayaran wajib diisi.", 400

    if not uploaded_file.filename:
        return "Pilih file bukti pembayaran.", 400

    filename = os.path.basename(uploaded_file.filename)
    extension = os.path.splitext(filename)[1].lower()

    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".pdf"}:
        return "Format file tidak didukung.", 400

    file_bytes = uploaded_file.read()

    if not file_bytes:
        return "File bukti pembayaran kosong.", 400

    if len(file_bytes) > 5 * 1024 * 1024:
        return "Ukuran file maksimal 5 MB.", 400

    try:
        # Mengasumsikan payment_proof bertipe BYTEA.
        # Pastikan tipe kolom Supabase sesuai sebelum deploy.
        conn = get_db()

        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE public.orders
                        SET payment_proof = %s,
                            payment_proof_name = %s
                        WHERE order_number = %s
                        """,
                        (
                            psycopg2.Binary(file_bytes),
                            filename,
                            order_number,
                        ),
                    )

                    if cur.rowcount == 0:
                        abort(404)
        finally:
            conn.close()

    except Exception:
        app.logger.exception("Gagal menyimpan bukti pembayaran")
        return "Bukti pembayaran gagal disimpan.", 500

    flash("Bukti pembayaran berhasil dikirim.", "success")
    return redirect(
        url_for("invoice", order_number=order_number)
    )


# =========================================================
# TRACK ORDER
# =========================================================

@app.route("/track-order", methods=["GET", "POST"])
def track_order():
    order = None
    searched = False

    if request.method == "POST":
        searched = True
        order_number = (
            request.form.get("order_number") or ""
        ).strip()

        if order_number:
            try:
                order = fetch_one(
                    """
                    SELECT *
                    FROM public.orders
                    WHERE order_number = %s
                    LIMIT 1
                    """,
                    (order_number,),
                )
            except Exception:
                app.logger.exception("Gagal melacak pesanan")
                return "Gagal melacak pesanan.", 500

    return render_template(
        "track_order.html",
        order=order,
        searched=searched,
    )


# =========================================================
# ADMIN ORDERS
# =========================================================

@app.route("/admin/orders")
def admin_orders():
    # Tambahkan autentikasi admin sebelum menggunakan route ini
    # di website produksi.
    try:
        orders = fetch_all(
            """
            SELECT *
            FROM public.orders
            ORDER BY created_at DESC NULLS LAST
            LIMIT 500
            """
        )
    except Exception:
        app.logger.exception("Gagal mengambil daftar pesanan")
        return "Gagal mengambil daftar pesanan.", 500

    return render_template("admin_orders.html", orders=orders)


# =========================================================
# REFUND
# =========================================================

@app.route("/refund", methods=["GET", "POST"])
def refund():
    if request.method == "POST":
        order_number = (
            request.form.get("order_number") or ""
        ).strip()
        reason = (request.form.get("reason") or "").strip()

        if not order_number or not reason:
            return "Nomor pesanan dan alasan refund wajib diisi.", 400

        try:
            order = fetch_one(
                """
                SELECT *
                FROM public.orders
                WHERE order_number = %s
                LIMIT 1
                """,
                (order_number,),
            )
        except Exception:
            app.logger.exception("Gagal memeriksa permintaan refund")
            return "Gagal memeriksa pesanan.", 500

        if not order:
            return "Pesanan tidak ditemukan.", 404

        # Belum mengubah status pesanan secara otomatis.
        # Proses refund harus diverifikasi oleh admin.
        return render_template(
            "refund.html",
            order=order,
            reason=reason,
            submitted=True,
        )

    return render_template("refund.html", submitted=False)


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():
    try:
        fetch_one("SELECT 1 AS ok")
        return {"status": "ok", "database": "connected"}, 200
    except Exception:
        app.logger.exception("Health check database gagal")
        return {"status": "error", "database": "unavailable"}, 500


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(error):
    return "Halaman atau pesanan tidak ditemukan.", 404


@app.errorhandler(500)
def internal_error(error):
    app.logger.exception("Internal server error")
    return "Terjadi kesalahan pada server.", 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
