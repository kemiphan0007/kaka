import os
import sys

# Tambahkan root repository ke Python path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Impor aplikasi Flask dari app.py
from app import app

# Vercel menggunakan objek aplikasi ini sebagai entry point
