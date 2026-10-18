import os
import re
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
from flask import (
    Flask, request, render_template, redirect,
    url_for, flash, abort, jsonify
)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "CHANGE_ME_TO_A_LONG_RANDOM_SECRET_IN_VERCEL"
)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

logging.basicConfig(level=logging.INFO)

ALLOWED_PROOF_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".pdf"
}
PRODUCT_NAME = "SR17018 Powder Product"


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
        raise ValueError("Harga tidak tersedia.")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts[-1]) == 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        else:
            cleaned = "".join(parts)
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
        """
        SELECT *
        FROM public.orders
        WHERE order_number = %s
        LIMIT 1
        """,
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
