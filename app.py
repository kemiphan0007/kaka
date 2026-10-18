import os
import re
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, abort, jsonify
)
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)

PRODUCT_NAME = "SR17018 Powder Product"
ALLOWED_PROOF_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def get_db():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL belum diatur.")

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
        sslmode="require",
    )


def fetch_one(sql, params=()):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def fetch_all(sql, params=()):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def form_value(*names, default=""):
    for name in names:
        value = request.form.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def parse_price(value):
    if value is None:
        raise ValueError("Harga tidak tersedia.")

    cleaned = re.sub(r"[^0-9,.]", "", str(value).strip())
    if not cleaned:
        raise ValueError("Format harga tidak valid.")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = (
            "".join(parts[:-1]) + "." + parts[-1]
            if len(parts[-1]) == 2
            else "".join(parts)
        )
    elif "." in cleaned and len(cleaned.split(".")) > 2:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Format harga tidak valid.") from exc

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Harga harus lebih besar dari nol.")

    return amount


def new_order_number():
    return (
        "SN-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )


def get_order(order_number):
    return fetch_one(
        "SELECT * FROM public.orders WHERE order_number = %s LIMIT 1",
        (order_number,),
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if request.method == "POST":
        package = form_value("package", "package_name")
        price = form_value("price", "total_amount")
    else:
        package = (
            request.args.get("package")
            or request.args.get("package_name")
            or ""
        ).strip()
        price = (
            request.args.get("price")
            or request.args.get("total_amount")
            or ""
        ).strip()

    return render_template(
        "checkout.html",
        package=package,
        price=price,
    )


@app.route("/place-order", methods=["POST"])
def place_order():
    name = form_value("name", "customer_name")
    email = form_value("email", "customer_email")
    address = form_value("address", "shipping_address")
    package = form_value("package", "package_name")
    price = form_value("price", "total_amount")
    quantity_text = form_value("quantity", default="1")

    if not all([name, email, address, package, price]):
        return (
            "Data pesanan belum lengkap. Periksa nama, email, "
            "alamat, paket, dan harga.",
            400,
        )

    try:
        quantity = int(quantity_text)
        if quantity < 1 or quantity > 10000:
            raise ValueError("Jumlah tidak valid.")

        unit_price = parse_price(price)
        total_amount = unit_price * quantity
    except (ValueError, TypeError):
        return "Harga atau jumlah pesanan tidak valid.", 400

    order_number = new_order_number()

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
                            PRODUCT_NAME,
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
        app.logger.exception("Gagal menyimpan order %s", order_number)
        return "Pesanan gagal disimpan. Periksa Runtime Logs Vercel.", 500

    return render_template(
        "success.html",
        order_number=order_number,
        name=name,
        email=email,
        address=address,
        package=package,
        price=price,
        quantity=quantity,
        total_amount=total_amount,
    )
    # ============================================================
# INVOICE
# ============================================================

@app.route("/invoice/<order_number>")
def invoice(order_number):
    try:
        order = get_order(order_number)
    except Exception:
        app.logger.exception("Gagal mengambil invoice")
        return "Gagal mengambil invoice.", 500

    if not order:
        abort(404)

    return render_template("invoice.html", order=order)


# ============================================================
# PAYMENT
# ============================================================

@app.route("/payment", methods=["GET", "POST"])
def payment():
    order_number = (
        request.values.get("order_number")
        or request.values.get("order")
        or ""
    ).strip()

    if not order_number:
        return render_template("payment.html", order=None)

    try:
        order = get_order(order_number)
    except Exception:
        app.logger.exception("Gagal mengambil data pembayaran")
        return "Gagal mengambil data pembayaran.", 500

    if not order:
        abort(404)

    return render_template("payment.html", order=order)


# ============================================================
# PAYMENT PROOF PAGE
# ============================================================

@app.route("/payment-proof/<order_number>", methods=["GET"])
def payment_proof_page(order_number):
    try:
        order = get_order(order_number)
    except Exception:
        app.logger.exception("Gagal mengambil pesanan")
        return "Gagal mengambil pesanan.", 500

    if not order:
        abort(404)

    return render_template(
        "payment_verification.html",
        order=order,
        order_number=order_number,
    )


@app.route("/payment-proof", methods=["GET", "POST"])
def payment_proof():
    if request.method == "GET":
        order_number = (
            request.args.get("order_number") or ""
        ).strip()

        order = None
        if order_number:
            try:
                order = get_order(order_number)
            except Exception:
                app.logger.exception("Gagal mengambil pesanan")
                return "Gagal mengambil pesanan.", 500

            if not order:
                abort(404)

        return render_template(
            "payment_verification.html",
            order=order,
            order_number=order_number,
        )

    order_number = form_value("order_number")
    uploaded = (
        request.files.get("payment_proof")
        or request.files.get("proof")
    )

    if not order_number or not uploaded or not uploaded.filename:
        return (
            "Nomor pesanan dan file bukti pembayaran wajib diisi.",
            400,
        )

    filename = secure_filename(uploaded.filename)
    extension = os.path.splitext(filename)[1].lower()

    if extension not in ALLOWED_PROOF_EXTENSIONS:
        return (
            "Format file harus JPG, JPEG, PNG, WEBP, atau PDF.",
            400,
        )

    file_bytes = uploaded.read()
    if not file_bytes:
        return "File bukti pembayaran kosong.", 400

    conn = None
    try:
        conn = get_db()

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE public.orders
                    SET payment_proof = %s,
                        payment_proof_name = %s,
                        status = %s,
                        payment_status = %s,
                        order_status = %s
                    WHERE order_number = %s
                    """,
                    (
                        psycopg2.Binary(file_bytes),
                        filename,
                        "Payment Verification",
                        "verification",
                        "payment_verification",
                        order_number,
                    ),
                )

                if cur.rowcount == 0:
                    abort(404)

    except Exception:
        app.logger.exception(
            "Gagal menyimpan bukti pembayaran untuk %s",
            order_number,
        )
        return "Bukti pembayaran gagal disimpan.", 500

    finally:
        if conn is not None:
            conn.close()

    flash(
        "Bukti pembayaran berhasil dikirim dan menunggu verifikasi.",
        "success",
    )

    return redirect(
        url_for("track_order", order_number=order_number)
    )


# ============================================================
# TRACK ORDER
# ============================================================

@app.route("/track-order", methods=["GET", "POST"])
def track_order():
    if request.method == "GET":
        order_number = (
            request.args.get("order_number") or ""
        ).strip()
    else:
        order_number = form_value("order_number", "order")

    order = None
    searched = bool(order_number)

    if order_number:
        try:
            order = get_order(order_number)
        except Exception:
            app.logger.exception("Gagal melacak pesanan")
            return "Gagal melacak pesanan.", 500

    return render_template(
        "track_order.html",
        order=order,
        searched=searched,
    )
    # ============================================================
# ADMIN ORDERS
# ============================================================

@app.route("/admin/orders")
def admin_orders():
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

    return render_template(
        "admin_orders.html",
        orders=orders,
    )


# ============================================================
# REFUND REQUEST
# Catatan: route ini mengirim permintaan, bukan refund otomatis.
# ============================================================

@app.route("/refund", methods=["GET", "POST"])
def refund():
    if request.method == "POST":
        order_number = form_value("order_number")
        reason = form_value("reason")

        if not order_number or not reason:
            return (
                "Nomor pesanan dan alasan refund wajib diisi.",
                400,
            )

        try:
            order = get_order(order_number)
        except Exception:
            app.logger.exception(
                "Gagal memeriksa pesanan untuk refund"
            )
            return "Gagal memeriksa pesanan.", 500

        if not order:
            return "Pesanan tidak ditemukan.", 404

        return render_template(
            "refund.html",
            order=order,
            reason=reason,
            submitted=True,
        )

    return render_template(
        "refund.html",
        submitted=False,
    )


# ============================================================
# DATABASE HEALTH CHECK
# ============================================================

@app.route("/health")
def health():
    try:
        fetch_one("SELECT 1 AS ok")
        return jsonify(
            status="ok",
            database="connected",
        ), 200

    except Exception:
        app.logger.exception("Health check database gagal")
        return jsonify(
            status="error",
            database="unavailable",
        ), 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return "Halaman atau pesanan tidak ditemukan.", 404


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
