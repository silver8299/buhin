# Flask 기본 로그인 시스템 + 발주자 / 검사자 계정 예제

from flask import Flask, render_template, redirect, url_for, request, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import mariadb
from datetime import datetime


# MariaDB 연결 설정
def get_db_connection():
    return mariadb.connect(
        user='root',
        password='@lina304162',
        host='localhost',
        port=3306,
        database='buhin_management'
    )

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 세션 암호화를 위한 키

# 샘플 사용자 데이터 (DB 대신 메모리에서 관리)
users = {
    'order_mgr': {
        'password': generate_password_hash('order123'),
        'role': 'order'
    },
    'inspect_mgr': {
        'password': generate_password_hash('inspect123'),
        'role': 'inspect'
    }
}

@app.route('/')
def home():
    # 로그인 되어 있으면 대시보드로, 아니면 로그인 페이지로 이동
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users.get(username)
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            session['role'] = user['role']
            return redirect(url_for('dashboard'))
        # 로그인 실패 시 에러 메시지 전달
        return render_template('login.html', error='ログインに失敗しました：ユーザー名またはパスワードが間違っています。')

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    # 로그인 안 되어 있으면 로그인 페이지로 이동
    if 'username' not in session:
        return redirect(url_for('login'))

    role = session['role']
    return render_template('dashboard.html', role=role, username=session['username'])

@app.route('/logout')
def logout():
    # 로그아웃 시 세션 삭제
    session.clear()
    return redirect(url_for('login'))

#발주자만 권한 가진 업무
@app.route('/order', methods=['GET'])
def order_form():
    # 발주자만 접근 가능
    if 'username' not in session or session.get('role') != 'order':
        return redirect(url_for('login'))
    return render_template('order_form.html')

#발주데이터 입력
@app.route('/submit_order', methods=['POST'])
def submit_order():
    if 'username' not in session or session.get('role') != 'order':
        return redirect(url_for('login'))

    # 폼 값 추출
    order_number = request.form.get('order_number', '').strip()
    part_number = request.form.get('part_number', '').strip()
    part_name = request.form.get('part_name', '').strip()
    quantity = request.form.get('quantity', '').strip()
    order_date = request.form.get('order_date', '').strip()
    supplier_name = request.form.get('supplier_name', '').strip()
    data_location = request.form.get('data_location', '').strip()
    remarks = request.form.get('remarks', '').strip()
    ordered_by = session['username']

    # 누락된 필드 확인
    missing_fields = []
    if not order_number:
        missing_fields.append("発注番号")
    if not part_number:
        missing_fields.append("部品番号")
    if not part_name:
        missing_fields.append("部品名")
    if not quantity:
        missing_fields.append("発注数量")
    if not order_date:
        missing_fields.append("発注日")
    if not supplier_name:
        missing_fields.append("供給先")
    if not data_location:
        missing_fields.append("データロケーション")

    # 오류 처리
    if missing_fields:
        missing_str = "、".join(missing_fields)
        flash(f"❌ 次の項目が未入力です: {missing_str}。すべて入力してください。")
        return redirect(url_for('order_form'))

    # DB 저장
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO ordered_parts (
                order_number, part_number, part_name,
                quantity, order_date, supplier_name,
                remarks, ordered_by, data_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_number, part_number, part_name,
            quantity, order_date, supplier_name,
            remarks, ordered_by, data_location
        ))
        conn.commit()
        flash("✅ 発注情報を保存しました。")
    except Exception as e:
        conn.rollback()
        flash(f"❌ データベースエラー: {e}")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/receive', methods=['GET'])
def receive_form():
    # 🔒 로그인 + 발주자(role=order)만 접근 가능
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが入荷登録できます。")
        return redirect(url_for('dashboard'))
    return render_template('received_form.html')


#입고데이터입력
@app.route('/submit_receipt', methods=['POST'])
def submit_receipt():
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが入荷登録できます。")
        return redirect(url_for('dashboard'))

    order_number = request.form.get('order_number')
    received_date = request.form.get('received_date')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. ordered_parts에서 해당 발주번호 조회
    cursor.execute("SELECT * FROM ordered_parts WHERE order_number = %s", (order_number,))
    order_data = cursor.fetchone()

    # 2. 유효성 검사
    if not order_data:
        flash("❌ 入力した発注番号は存在しません。")
        conn.close()
        return redirect(url_for('receive_form'))

    if received_date < str(order_data['order_date']):
        flash("❌ 発注日より前の入荷日は登録できません。")
        conn.close()
        return redirect(url_for('receive_form'))

    # 3. 중복 검사
    cursor.execute("SELECT * FROM received_parts WHERE order_number = %s", (order_number,))
    if cursor.fetchone():
        flash("❌ この発注番号はすでに入荷登録されています。")
        conn.close()
        return redirect(url_for('receive_form'))

    # 4. 복사 & 삭제
    insert_query = """
        INSERT INTO received_parts 
        (order_number, part_number, part_name, quantity, order_date, supplier_name, remarks, data_location, received_date, ordered_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cursor.execute(insert_query, (
        order_data['order_number'], order_data['part_number'], order_data['part_name'],
        order_data['quantity'], order_data['order_date'], order_data['supplier_name'],
        order_data['remarks'], order_data['data_location'], received_date, order_data['ordered_by']
    ))

    # 5. ordered_parts에서 삭제
    cursor.execute("DELETE FROM ordered_parts WHERE order_number = %s", (order_number,))

    conn.commit()
    conn.close()

    flash("✅ 入荷情報を登録しました（発注データは入荷データに移動されました）。")
    return redirect(url_for('dashboard'))

#발주데이터 조회
@app.route('/order_list')
def order_list():
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが閲覧可能です。")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM ordered_parts")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('order_data.html', data=rows)

# 발주 테이블 삭제 라우트
@app.route('/delete_order', methods=['POST'])
def delete_order():
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが削除可能です。")
        return redirect(url_for('dashboard'))

    order_number = request.form['order_number']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM ordered_parts WHERE order_number = ?", (order_number,))
    conn.commit()
    cur.close()
    conn.close()
    flash(f"✅ 発注番号「{order_number}」を削除しました。")
    return redirect(url_for('order_list'))

#입고(미검사)데이터 조회
@app.route('/uninspected_parts')
def uninspected_parts():
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが閲覧できます。")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM received_parts")
    parts = cursor.fetchall()
    conn.close()

    return render_template("uninspected_parts.html", parts=parts)

#입고(미검사) 데이터 삭제는 발주 담당자만
@app.route('/delete_received_part', methods=['POST'])
def delete_received_part():
    if 'username' not in session or session.get('role') != 'order':
        flash("⚠️ 発注担当者のみが削除できます。")
        return redirect(url_for('dashboard'))

    order_number = request.form.get('order_number')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM received_parts WHERE order_number = %s", (order_number,))
    conn.commit()
    conn.close()
    flash("✅ 対象データを削除しました。")
    return redirect(url_for('uninspected_parts'))

#마리아디비 연결 성패여부
@app.route('/db_test')
def db_test():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT NOW();")  # 현재 시간 조회
        result = cur.fetchone()
        cur.close()
        conn.close()
        return f"✅ MariaDB 연결 성공! 현재 시간: {result[0]}"
    except Exception as e:
        return f"❌ MariaDB 연결 실패: {e}"
    
if __name__ == '__main__':
    app.run(debug=True)