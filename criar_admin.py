"""Cria (ou promove) uma conta de administrador.

Uso:  python criar_admin.py
"""
import getpass
import sqlite3

from werkzeug.security import generate_password_hash

from app import DB_PATH, init_db

init_db()

nome = input("Nome: ").strip() or "Admin"
apelido = ""
email = input("Email: ").strip().lower()
password = getpass.getpass("Palavra-passe (mín. 8 caracteres): ")

if not email or len(password) < 8:
    raise SystemExit("Email em falta ou palavra-passe demasiado curta.")

with sqlite3.connect(DB_PATH) as db:
    try:
        db.execute(
            "INSERT INTO utilizadores (nome, apelido, email, password_hash, papel) "
            "VALUES (?, ?, ?, ?, 'admin')",
            (nome, apelido, email, generate_password_hash(password)),
        )
        print(f"Administrador criado: {email}")
    except sqlite3.IntegrityError:
        print("Esse email já existe. Use outro, ou apague o utilizador primeiro.")
