from flask import Flask, request, jsonify
from flask_cors import CORS

import sqlite3
from collections import defaultdict
import heapq
from datetime import datetime
import hashlib

app = Flask(__name__)
CORS(app)

loan_heap = []
transactions_graph = defaultdict(list)
user_info_map = {}


def init_db():
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT,
                        email TEXT UNIQUE,
                        mobile TEXT,
                        dob TEXT,
                        password TEXT,
                        account_number TEXT UNIQUE,
                        balance REAL DEFAULT 0,
                        created_at TEXT,
                        updated_at TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender_id INTEGER,
                        receiver_id INTEGER,
                        amount REAL,
                        timestamp TEXT)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS loan_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        amount REAL,
                        priority_score INTEGER)''')

    conn.commit()
    conn.close()


def generate_account_number():
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(account_number) FROM users")
    result = cursor.fetchone()[0]
    conn.close()
    if result is None:
        return "10000"
    return str(int(result) + 1)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def load_user_info():
    global user_info_map
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, account_number FROM users")
    rows = cursor.fetchall()
    conn.close()
    user_info_map = {row[0]: f"{row[1]} - {row[2]}" for row in rows}


@app.route("/create_account", methods=["POST"])
def create_account():
    data = request.json
    conn = sqlite3.connect("bank.db")
    try:
        account_number = generate_account_number()
        hashed_pw = hash_password(data["password"])
        now = datetime.now().isoformat()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, email, mobile, dob, password, account_number, balance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data["name"], data["email"], data["mobile"], data["dob"], hashed_pw, account_number, data["amount"], now,
             now))
        conn.commit()
        load_user_info()
        return jsonify({"message": "Account created successfully.", "account_number": account_number}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email must be unique."}), 400
    finally:
        conn.close()


@app.route("/login", methods=["POST"])
def login():
    data = request.json
    if not data.get("email") or not data.get("password"):
        return jsonify({"error": "Email and password are required."}), 400

    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, password, account_number FROM users WHERE email = ?", (data["email"],))
    user = cursor.fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "Email not registered."}), 404

    if user[2] != hash_password(data["password"]):
        return jsonify({"error": "Incorrect password."}), 400

    return jsonify({"id": user[0], "name": user[1], "account_number": user[3]}), 200


@app.route("/deposit", methods=["POST"])
def deposit():
    data = request.json
    user_id = data["user_id"]
    amount = data["amount"]

    if amount <= 0:
        return jsonify({"error": "Deposit amount must be positive."}), 400

    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    cursor.execute("UPDATE users SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, timestamp, user_id))
    if cursor.rowcount == 0:
        return jsonify({"error": "User not found."}), 404
    conn.commit()
    conn.close()
    return jsonify({"message": f"Deposited ₹{amount} to your account."})


@app.route("/withdraw", methods=["POST"])
def withdraw():
    data = request.json
    user_id = data["user_id"]
    amount = data["amount"]

    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        return jsonify({"error": "User not found."}), 404

    if result[0] < amount:
        return jsonify({"error": "Insufficient balance."}), 400

    timestamp = datetime.now().isoformat()
    cursor.execute("UPDATE users SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, timestamp, user_id))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Withdrawn ₹{amount} from your account."})


@app.route("/balance", methods=["GET"])
def balance():
    user_id = request.args.get("user_id")
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return jsonify({"balance": result[0]})
    return jsonify({"error": "User not found."}), 404


@app.route("/list_users", methods=["GET"])
def list_users():
    user_id = request.args.get("user_id")
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, account_number FROM users WHERE id != ?", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    users = [{"id": r[0], "name": r[1] + " - " + r[2]} for r in rows]
    return jsonify({"users": users})


@app.route("/transfer", methods=["POST"])
def transfer():
    data = request.json
    sender_id = data["sender_id"]
    receiver_id = data["receiver_id"]
    amount = data["amount"]

    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE id = ?", (sender_id,))
    sender = cursor.fetchone()
    cursor.execute("SELECT id FROM users WHERE id = ?", (receiver_id,))
    receiver = cursor.fetchone()

    if sender_id == receiver_id:
        return jsonify({"error": "Invalid sender or receiver."}), 400

    if not sender or not receiver:
        return jsonify({"error": "Invalid sender or receiver."}), 400

    if sender[0] < amount:
        return jsonify({"error": "Insufficient balance."}), 400

    timestamp = datetime.now().isoformat()
    cursor.execute("UPDATE users SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, timestamp, sender_id))
    cursor.execute("UPDATE users SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, timestamp, receiver_id))
    cursor.execute("INSERT INTO transactions (sender_id, receiver_id, amount, timestamp) VALUES (?, ?, ?, ?)", (sender_id, receiver_id, amount, timestamp))
    conn.commit()
    conn.close()

    load_user_info()
    transactions_graph[sender_id].append((receiver_id, amount, timestamp))
    return jsonify({"message": f"Transferred ₹{amount}."})


@app.route("/show_transactions", methods=["GET"])
def show_transactions():
    user_id = int(request.args.get("user_id"))
    load_user_info()
    transaction_list = []
    for sender, transactions in transactions_graph.items():
        for receiver, amount, timestamp in transactions:
            if sender == user_id or receiver == user_id:
                date_str = datetime.fromisoformat(timestamp).strftime("%d-%m-%Y %H:%M:%S")
                tx_type = "Send" if sender == user_id else "Received"
                transaction_list.append({
                    "date": date_str,
                    "type": tx_type,
                    "amount": amount,
                    "from": user_info_map.get(sender, f"User {sender}"),
                    "to": user_info_map.get(receiver, f"User {receiver}")
                })
    return jsonify({"transactions": transaction_list})


@app.route("/request_loan", methods=["POST"])
def request_loan():
    data = request.json
    user_id = data["user_id"]
    amount = data["amount"]

    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, created_at FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"error": "User not found."}), 404

    balance = user[0]
    created_at_str = user[1]
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE sender_id = ? OR receiver_id = ?", (user_id, user_id))
    tx_count = cursor.fetchone()[0]

    try:
        created_at = datetime.fromisoformat(created_at_str)
    except:
        created_at = datetime.now()

    days_active = (datetime.now() - created_at).days

    priority_score = (balance // 1000) + (days_active // 30) + min(tx_count, 50) + max(0, 100 - amount // 1000)

    cursor.execute("INSERT INTO loan_requests (user_id, amount, priority_score) VALUES (?, ?, ?)",
                   (user_id, amount, priority_score))
    conn.commit()
    conn.close()

    heapq.heappush(loan_heap, (-priority_score, user_id, amount))
    return jsonify({"message": f"Loan requested for ₹{amount}. Priority calculated: {priority_score}"})


@app.route("/approve_loan", methods=["POST"])
def approve_loan():
    if not loan_heap:
        return jsonify({"message": "No loan requests in the queue."})
    priority_score, user_id, amount = heapq.heappop(loan_heap)
    conn = sqlite3.connect("bank.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Approved loan of ₹{amount} to you with priority {-priority_score}."})


@app.route("/list_loan_requests", methods=["GET"])
def list_loan_requests():
    load_user_info()
    result = []
    for entry in sorted(loan_heap, reverse=True):
        priority, user_id, amount = entry
        result.append({
            "user": user_info_map.get(user_id, f"User {user_id}"),
            "amount": amount,
            "priority": -priority
        })
    return jsonify({"loan_requests": result})


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
