from flask import Flask, render_template, request, redirect, url_for, session, Response
import sqlite3
import csv
import io
from datetime import date

app = Flask(__name__)
app.secret_key = "smart_attendance_secret_key_v2"

DATABASE = "attendance.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table (role: 'admin' or 'student')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            student_id INTEGER,
            FOREIGN KEY (student_id) REFERENCES students (id)
        )
    """)

    # Students table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            email TEXT
        )
    """)

    # Attendance table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (id),
            UNIQUE(student_id, attendance_date)
        )
    """)

    # Default Admin account add karna
    cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin")
        )

    conn.commit()
    conn.close()

init_db()

@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session and "role" in session:
        if session.get("role") == "admin":
            return redirect(url_for("dashboard"))
        elif session.get("role") == "student":
            return redirect(url_for("student_dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session.clear()
            session["user"] = user["username"]
            session["role"] = user["role"]
            session["student_id"] = user["student_id"]

            if user["role"] == "admin":
                return redirect(url_for("dashboard"))
            else:
                return redirect(url_for("student_dashboard"))
        else:
            error = "Invalid Username/Roll No or Password!"

    return render_template("login.html", error=error)

# ================= ADMIN ROUTES =================

@app.route("/dashboard")
def dashboard():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    today_str = date.today().strftime("%Y-%m-%d")
    conn = get_db_connection()

    total_students = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]

    present_today = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE attendance_date = ? AND status = 'Present'",
        (today_str,)
    ).fetchone()[0]

    absent_today = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE attendance_date = ? AND status = 'Absent'",
        (today_str,)
    ).fetchone()[0]

    marked_total = present_today + absent_today
    percentage = round((present_today / marked_total) * 100, 1) if marked_total > 0 else 0.0

    daily_records = conn.execute("""
        SELECT attendance_date,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent
        FROM attendance
        GROUP BY attendance_date
        ORDER BY attendance_date DESC
    """).fetchall()

    daily_history = []
    for row in daily_records:
        day_total = row["total"]
        day_present = row["present"]
        day_pct = round((day_present / day_total) * 100, 1) if day_total > 0 else 0.0
        daily_history.append({
            "date": row["attendance_date"],
            "total": day_total,
            "present": day_present,
            "absent": row["absent"],
            "percentage": day_pct
        })

    conn.close()

    return render_template(
        "dashboard.html",
        total_students=total_students,
        present_today=present_today,
        absent_today=absent_today,
        attendance_percentage=percentage,
        daily_history=daily_history
    )

@app.route("/students")
def students():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    conn = get_db_connection()
    students_list = conn.execute("SELECT * FROM students ORDER BY roll_no ASC").fetchall()
    conn.close()

    return render_template("students.html", students=students_list)

@app.route("/students/add", methods=["GET", "POST"])
def add_student():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        roll_no = request.form.get("roll_no", "").strip()
        name = request.form.get("name", "").strip()
        class_name = request.form.get("class_name", "").strip()
        email = request.form.get("email", "").strip()

        conn = get_db_connection()
        existing = conn.execute("SELECT * FROM students WHERE roll_no = ?", (roll_no,)).fetchone()

        if existing:
            error = f"Student with Roll No '{roll_no}' already exists!"
            conn.close()
        else:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO students (roll_no, name, class_name, email) VALUES (?, ?, ?, ?)",
                (roll_no, name, class_name, email)
            )
            student_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO users (username, password, role, student_id) VALUES (?, ?, ?, ?)",
                (roll_no, "student123", "student", student_id)
            )

            conn.commit()
            conn.close()
            return redirect(url_for("students"))

    return render_template("add_student.html", error=error)

@app.route("/students/delete/<int:student_id>")
def delete_student(student_id):
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    conn = get_db_connection()
    conn.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM users WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("students"))

@app.route("/attendance", methods=["GET", "POST"])
def mark_attendance():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    conn = get_db_connection()
    message = None

    if request.method == "POST":
        attendance_date = request.form.get("attendance_date")
        students_list = conn.execute("SELECT id FROM students").fetchall()

        for student in students_list:
            sid = student["id"]
            status = request.form.get(f"status_{sid}", "Present")

            conn.execute("""
                INSERT INTO attendance (student_id, attendance_date, status)
                VALUES (?, ?, ?)
                ON CONFLICT(student_id, attendance_date) DO UPDATE SET status = excluded.status
            """, (sid, attendance_date, status))

        conn.commit()
        message = f"Attendance saved successfully for date: {attendance_date}"
        selected_date = attendance_date
    else:
        selected_date = request.args.get("date", date.today().strftime("%Y-%m-%d"))

    records = conn.execute(
        "SELECT student_id, status FROM attendance WHERE attendance_date = ?",
        (selected_date,)
    ).fetchall()
    existing_attendance = {row["student_id"]: row["status"] for row in records}

    students_list = conn.execute("SELECT * FROM students ORDER BY roll_no ASC").fetchall()
    conn.close()

    return render_template(
        "attendance.html",
        students=students_list,
        selected_date=selected_date,
        existing_attendance=existing_attendance,
        message=message
    )

@app.route("/reports")
def reports():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    conn = get_db_connection()
    students_list = conn.execute("SELECT * FROM students ORDER BY roll_no ASC").fetchall()

    reports_data = []
    for s in students_list:
        total = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?", (s["id"],)).fetchone()[0]
        present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (s["id"],)).fetchone()[0]
        absent = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Absent'", (s["id"],)).fetchone()[0]

        pct = round((present / total) * 100, 1) if total > 0 else 0.0

        reports_data.append({
            "roll_no": s["roll_no"],
            "name": s["name"],
            "class_name": s["class_name"],
            "total_classes": total,
            "present_count": present,
            "absent_count": absent,
            "percentage": pct
        })

    conn.close()
    return render_template("report.html", reports_data=reports_data)

@app.route("/reports/export")
def export_csv():
    if "user" not in session or session.get("role") != "admin":
        session.clear()
        return redirect(url_for("login"))

    conn = get_db_connection()
    students_list = conn.execute("SELECT * FROM students ORDER BY roll_no ASC").fetchall()

    distinct_dates_rows = conn.execute("SELECT DISTINCT attendance_date FROM attendance ORDER BY attendance_date ASC").fetchall()
    all_dates = [row["attendance_date"] for row in distinct_dates_rows]

    att_rows = conn.execute("SELECT student_id, attendance_date, status FROM attendance").fetchall()
    att_map = {(row["student_id"], row["attendance_date"]): row["status"] for row in att_rows}

    output = io.StringIO()
    writer = csv.writer(output)

    headers = ["Roll Number", "Student Name", "Class"] + all_dates + ["Total Present", "Total Absent", "Attendance %"]
    writer.writerow(headers)

    for s in students_list:
        row = [s["roll_no"], s["name"], s["class_name"]]
        present_cnt = 0
        absent_cnt = 0

        for d in all_dates:
            status = att_map.get((s["id"], d), "-")
            if status == "Present":
                row.append("P")
                present_cnt += 1
            elif status == "Absent":
                row.append("A")
                absent_cnt += 1
            else:
                row.append("-")

        total_marked = present_cnt + absent_cnt
        pct = round((present_cnt / total_marked) * 100, 1) if total_marked > 0 else 0.0

        row.extend([present_cnt, absent_cnt, f"{pct}%"])
        writer.writerow(row)

    conn.close()
    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=attendance_register_detailed.csv"}
    )

# ================= STUDENT ROUTES =================

@app.route("/student-dashboard")
def student_dashboard():
    if "user" not in session or session.get("role") != "student":
        session.clear()
        return redirect(url_for("login"))

    student_id = session.get("student_id")
    conn = get_db_connection()

    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        session.clear()
        return redirect(url_for("login"))

    total = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ?", (student_id,)).fetchone()[0]
    present = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (student_id,)).fetchone()[0]
    absent = conn.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Absent'", (student_id,)).fetchone()[0]
    pct = round((present / total) * 100, 1) if total > 0 else 0.0

    history = conn.execute(
        "SELECT attendance_date, status FROM attendance WHERE student_id = ? ORDER BY attendance_date DESC",
        (student_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "student_dashboard.html",
        student=student,
        total_classes=total,
        present_count=present,
        absent_count=absent,
        percentage=pct,
        history=history
    )

@app.route("/student/export")
def export_student_csv():
    if "user" not in session or session.get("role") != "student":
        session.clear()
        return redirect(url_for("login"))

    student_id = session.get("student_id")
    conn = get_db_connection()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()

    history = conn.execute(
        "SELECT attendance_date, status FROM attendance WHERE student_id = ? ORDER BY attendance_date DESC",
        (student_id,)
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Roll Number", "Student Name", "Class", "Date", "Status"])

    for record in history:
        writer.writerow([
            student["roll_no"],
            student["name"],
            student["class_name"],
            record["attendance_date"],
            record["status"]
        ])

    output.seek(0)
    filename = f"attendance_report_{student['roll_no']}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)