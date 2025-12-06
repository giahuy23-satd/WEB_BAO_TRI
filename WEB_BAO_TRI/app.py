# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from models import get_engine, create_all, create_default_admin_if_not_exists, User, Customer, WorkOrder, OrderImage, OrderHistory
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from sqlalchemy import func
from datetime import datetime
from sqlalchemy.orm import joinedload

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
ALLOWED_EXT = {'png','jpg','jpeg','gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = 'change_me_now'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

engine = create_all()
Session = sessionmaker(bind=engine)

# create default admin
s = Session()
create_default_admin_if_not_exists(s)
s.close()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('Bạn không có quyền truy cập trang này.')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapper
    return deco

# auth
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        session_db = Session()
        try:
            if session_db.query(User).filter(User.email==email).first():
                flash('Email đã được sử dụng.')
                return redirect(url_for('register'))
            u = User(full_name=full_name, email=email, phone=phone, password_hash=generate_password_hash(password), role='customer')
            session_db.add(u)
            session_db.commit()
            flash('Đăng ký thành công. Hãy đăng nhập.')
            return redirect(url_for('login'))
        finally:
            session_db.close()
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = request.form.get('email')
        password = request.form.get('password')
        session_db = Session()
        try:
            u = session_db.query(User).filter(User.email==email).first()
            if not u or not check_password_hash(u.password_hash, password):
                flash('Email hoặc mật khẩu không đúng.')
                return redirect(url_for('login'))
            # set session
            session['user_id'] = u.id
            session['full_name'] = u.full_name
            session['role'] = u.role
            flash('Đăng nhập thành công.')
            if u.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif u.role == 'technician':
                return redirect(url_for('technician'))
            elif u.role == 'delivery':
                return redirect(url_for('delivery_dashboard'))
            else:
                return redirect(url_for('customer_choice'))
        finally:
            session_db.close()
    return render_template('login.html')

# ----- Simple review storage -----
# Bạn có 2 lựa chọn: tạo table Review (dưới) hoặc lưu tạm vào OrderHistory.
# Dưới đây là route handler giả lập: lưu review vào bảng order_history (note) — không cần migration.

@app.route('/submit_review', methods=['POST'])
@login_required
def submit_review():
    order_id = request.form.get('order_id')
    rating = request.form.get('rating')
    comment = request.form.get('comment', '')
    db = Session()
    try:
        # kiểm tra đơn tồn tại
        order = db.query(WorkOrder).get(order_id)
        if not order:
            flash('Không tìm thấy đơn để đánh giá.', 'danger')
            return redirect(url_for('my_orders'))

        # Lưu vào OrderHistory làm ghi chú đánh giá (nếu muốn riêng, bạn có thể thêm model Review)
        note = f"Đánh giá: {rating} sao. Nhận xét: {comment}"
        hist = OrderHistory(order_id=order.id, old_status=order.status, new_status=order.status, changed_by=session['user_id'], note=note)
        db.add(hist)
        db.commit()
        flash('Cảm ơn bạn đã đánh giá!', 'success')
    except Exception as e:
        db.rollback()
        flash('Lỗi khi gửi đánh giá: '+str(e), 'danger')
    finally:
        db.close()
    return redirect(url_for('my_orders'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/maintenance')
def maintenance():
    return render_template("customer_choice=.html")


@app.route('/')
def index():
    return render_template('index.html')

# Customer quick form (anonymous or logged in)
@app.route('/customer')
def customer_choice():
    return render_template('customer_choice.html')

@app.route('/customer/form/<order_type>', methods=['GET','POST'])
@login_required
def customer_form(order_type):
    if order_type not in ('baotri','suachua'):
        flash('Loại không hợp lệ')
        return redirect(url_for('customer_choice'))

    db = Session()
    try:
        # --- LẤY USER ĐĂNG NHẬP ---
        uid = session.get("user_id")
        user = db.query(User).get(uid)

        if not user:
            flash("Không tìm thấy tài khoản người dùng!")
            return redirect(url_for('customer_choice'))

        # --- TÌM HOẶC TẠO CUSTOMER TƯƠNG ỨNG ---
        customer = db.query(Customer).filter(Customer.email == user.email).first()

        if not customer:
            customer = Customer(
                full_name=user.full_name,
                phone=user.phone,
                email=user.email,
                address=""   # nếu muốn để trống
            )
            db.add(customer)
            db.flush()

        if request.method == 'POST':
            phone = request.form.get('phone')
            address = request.form.get('address')
            description = request.form.get('description')

            # Cập nhật thông tin khách
            customer.phone = phone
            customer.address = address
            db.add(customer)

            # Tạo đơn
            order = WorkOrder(
                customer_id=customer.id,
                order_type=order_type,
                description=description
            )

            db.add(order)
            db.commit()

            flash(f'Đã tạo đơn thành công! Mã đơn: {order.id}')
            return redirect(url_for('customer_choice'))

        return render_template('customer_form.html', order_type=order_type, customer=customer)

    except Exception as e:
        db.rollback()
        flash("Lỗi: " + str(e))
    finally:
        db.close()

# Auth user creates order (registered customer)
@app.route('/my/orders')
@login_required
def my_orders():
    uid = session['user_id']
    # find user's customer record by email or phone (simple approach)
    db = Session()
    try:
        user = db.query(User).get(uid)
        cust = None
        if user and user.email:
            cust = db.query(Customer).filter(Customer.email==user.email).first()
        orders = []
        if cust:
            orders = db.query(WorkOrder).filter(WorkOrder.customer_id==cust.id).order_by(WorkOrder.created_at.desc()).all()
        return render_template('my_orders.html', orders=orders)
    finally:
        db.close()

# Technician view (filter)
@app.route('/technician')
@role_required('technician', 'admin')
def technician():
    filter_status = request.args.get('status')  # moi | dang_xu_ly | da_hoan_thanh

    db = Session()
    try:
        q = db.query(WorkOrder).options(
            joinedload(WorkOrder.customer),
            joinedload(WorkOrder.technician)
        )

        # Nếu là kỹ thuật viên → chỉ thấy đơn của mình
        if session.get('role') == 'technician':
            q = q.filter(WorkOrder.technician_id == session['user_id'])

        # Lọc theo trạng thái (nếu có)
        if filter_status in ("moi", "dang_xu_ly", "da_hoan_thanh"):
            q = q.filter(WorkOrder.status == filter_status)

        orders = q.order_by(WorkOrder.created_at.desc()).all()

        technicians = db.query(User).filter(User.role == "technician").all()

        return render_template(
            "tech_orders.html",
            orders=orders,
            technicians=technicians
        )
    finally:
        db.close()


# Admin overview
@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    db = Session()
    try:
        orders = db.query(WorkOrder).order_by(WorkOrder.created_at.desc()).all()

        technicians = []
        all_techs = db.query(User).filter(User.role == "technician").all()

        for t in all_techs:
            active = db.query(WorkOrder).filter(
                WorkOrder.technician_id == t.id,
                WorkOrder.status != "da_hoan_thanh"
            ).count()

            t.active_orders = active
            technicians.append(t)

        return render_template(
            "admin_orders.html",
            orders=orders,
            technicians=technicians
        )
    finally:
        db.close()



@app.route("/admin/accounts")
@role_required('admin')
def admin_accounts():
    db = Session()
    try:
        filter_role = request.args.get("role")

        if filter_role and filter_role.strip() != "":
            users = db.query(User).filter(User.role == filter_role).order_by(User.id.desc()).all()
        else:
            # TRƯỜNG HỢP "TẤT CẢ" → LẤY HẾT
            users = db.query(User).order_by(User.id.desc()).all()
            filter_role = ""   # quan trọng để dropdown hiển thị đúng

        return render_template(
            "admin_accounts.html",
            users=users,
            filter_role=filter_role,
            tab="accounts"
        )
    finally:
        db.close()




@app.route("/admin/update_role/<int:user_id>", methods=["POST"])
@role_required('admin')
def admin_update_role(user_id):
    new_role = request.form.get("role")

    db = Session()
    user = db.query(User).get(user_id)

    if not user:
        flash("Không tìm thấy tài khoản.")
        return redirect(url_for("admin_accounts"))

    user.role = new_role
    db.commit()
    db.close()

    flash("Cập nhật quyền thành công!")
    return redirect(url_for("admin_accounts"))


@app.route("/admin/orders")
@role_required("admin")
def admin_orders():
    order_type = request.args.get("type")        # baotri | suachua | None
    status = request.args.get("status")          # moi | dang_xu_ly | da_hoan_thanh | None

    db = Session()
    try:
        q = db.query(WorkOrder)

        # Lọc loại đơn
        if order_type in ("baotri", "suachua"):
            q = q.filter(WorkOrder.order_type == order_type)

        # Lọc trạng thái
        if status in ("moi", "dang_xu_ly", "da_hoan_thanh"):
            q = q.filter(WorkOrder.status == status)

        orders = q.order_by(WorkOrder.created_at.desc()).all()

        # Lấy technician + đếm số đơn đang xử lý
        technicians = []
        all_techs = db.query(User).filter(User.role == "technician").all()

        for t in all_techs:
            active = db.query(WorkOrder).filter(
                WorkOrder.technician_id == t.id,
                WorkOrder.status != "da_hoan_thanh"
            ).count()
            t.active_orders = active
            technicians.append(t)

        return render_template(
            "admin_orders.html",
            orders=orders,
            technicians=technicians,
            filter_type=order_type,
            filter_status=status
        )

    finally:
        db.close()



# Order detail
@app.route('/order/<int:order_id>', methods=['GET','POST'])
@login_required
def order_detail(order_id):
    db = Session()
    try:
        order = db.query(WorkOrder).get(order_id)
        if not order:
            flash('Không tìm thấy đơn.')
            return redirect(url_for('index'))

        # handle status update or image upload
        if request.method == 'POST':
            action = request.form.get('action')
            user_id = session['user_id']
            if action == 'update_status':
                new_status = request.form.get('status')
                note = request.form.get('note', '')
                if new_status in ('moi','dang_xu_ly','da_hoan_thanh'):
                    old = order.status
                    order.status = new_status
                    db.add(order)
                    hist = OrderHistory(order_id=order.id, old_status=old, new_status=new_status, changed_by=user_id, note=note)
                    db.add(hist)
                    db.commit()
                    flash('Cập nhật trạng thái thành công.')
                    return redirect(url_for('order_detail', order_id=order_id))
            elif action == 'upload_image' and 'image' in request.files:
                f = request.files['image']
                if f and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    # ensure unique name
                    ts = datetime.now().strftime('%Y%m%d%H%M%S%f')
                    filename = f"{order_id}_{ts}_{filename}"
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    f.save(save_path)
                    rel = os.path.join('uploads', filename)
                    img = OrderImage(order_id=order.id, file_path=rel, uploaded_by=session['user_id'])
                    db.add(img)
                    db.commit()
                    flash('Ảnh đã upload.')
                    return redirect(url_for('order_detail', order_id=order_id))
                else:
                    flash('File không hợp lệ.')
        # read images and history
        images = db.query(OrderImage).filter(OrderImage.order_id==order.id).order_by(OrderImage.created_at.desc()).all()
        history = db.query(OrderHistory).filter(OrderHistory.order_id==order.id).order_by(OrderHistory.created_at.desc()).all()
        return render_template('order_detail.html', order=order, images=images, history=history)
    finally:
        db.close()



def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXT

# Admin: assign technician
# ===== ADMIN: ASSIGN TECHNICIAN =====
@app.route("/admin/assign/<int:order_id>", methods=["POST"])
@role_required("admin")
def admin_assign(order_id):
    tech_id = request.form.get("technician_id")

    db = Session()
    try:
        order = db.query(WorkOrder).get(order_id)

        if not order:
            flash("Không tìm thấy đơn.", "danger")
            return redirect(url_for("admin_orders"))

        # Nếu admin bỏ chọn → kỹ thuật viên = None
        if not tech_id:
            order.technician_id = None
            db.commit()
            flash("Đã xoá kỹ thuật viên khỏi đơn.", "success")
            return redirect(url_for("admin_orders"))

        tech_id = int(tech_id)

        # Đếm số đơn chưa hoàn thành của technician
        active_orders = db.query(WorkOrder).filter(
            WorkOrder.technician_id == tech_id,
            WorkOrder.status != "da_hoan_thanh"
        ).count()

        MAX_ORDERS = 10

        if active_orders >= MAX_ORDERS:
            flash(
                f"Kỹ thuật viên này đã có {active_orders}/{MAX_ORDERS} đơn. "
                f"Chỉ được nhận tối đa {MAX_ORDERS} đơn!",
                "danger"
            )
            return redirect(url_for("admin_orders"))

        # Gán technician
        order.technician_id = tech_id

        # Nếu trạng thái đơn đang là 'moi' thì đổi thành 'dang_xu_ly'
        if order.status == "moi":
            order.status = "dang_xu_ly"

        db.commit()
        flash("Gán kỹ thuật viên thành công!", "success")

    except Exception as e:
        db.rollback()
        flash(f"Lỗi: {e}", "danger")
    finally:
        db.close()

    return redirect(url_for("admin_orders"))



# Admin: change user role
@app.route('/admin/change_role/<int:user_id>', methods=['POST'])
@role_required('admin')
def admin_change_role(user_id):
    new_role = request.form.get('role')
    if new_role not in ('customer','technician','admin'):
        flash('Role không hợp lệ.')
        return redirect(url_for('admin_dashboard'))
    db = Session()
    try:
        u = db.query(User).get(user_id)
        if u:
            u.role = new_role
            db.commit()
            flash('Đã cập nhật quyền.')
    finally:
        db.close()
    return redirect(url_for('admin_dashboard'))

# Reports: counts per month, per type, per technician
@app.route("/admin/admin_reports")
@role_required('admin')
def admin_reports():
    db = Session()

    # A. Thống kê theo tháng
    per_month = db.query(
        func.date_format(WorkOrder.created_at, '%Y-%m').label('month'),
        func.count(WorkOrder.id)
    ).group_by('month').order_by('month').all()

    monthly_data = {
        "labels": [m[0] for m in per_month],
        "datasets": [{
            "label": "Số lượng đơn theo tháng",
            "data": [m[1] for m in per_month]
        }]
    }

    # B. Loại đơn
    per_type = db.query(
        WorkOrder.order_type,
        func.count(WorkOrder.id)
    ).group_by(WorkOrder.order_type).all()

    type_data = {
        "labels": [t[0] for t in per_type],
        "datasets": [{
            "label": "Loại đơn",
            "data": [t[1] for t in per_type]
        }]
    }

    # C. Theo kỹ thuật viên
    per_tech = db.query(
        User.full_name,
        func.count(WorkOrder.id)
    ).join(WorkOrder, WorkOrder.technician_id == User.id
    ).group_by(User.full_name).all()

    tech_data = {
        "labels": [t[0] for t in per_tech],
        "datasets": [{
            "label": "Số đơn / kỹ thuật viên",
            "data": [t[1] for t in per_tech]
        }]
    }

    db.close()

    return render_template(
        "admin_reports.html",
        monthly_data=monthly_data,
        type_data=type_data,
        tech_data=tech_data,
        tab="admin_reports"
    )


    # ---- C. Thống kê theo kỹ thuật viên ----
    tech_raw = db.execute("""
        SELECT u.full_name, COUNT(w.id)
        FROM work_order w
        LEFT JOIN user u ON w.technician_id = u.id
        WHERE w.technician_id IS NOT NULL
        GROUP BY u.full_name
    """).fetchall()

    tech_labels = [row[0] for row in tech_raw]
    tech_counts = [row[1] for row in tech_raw]

    tech_data = {
        "labels": tech_labels,
        "datasets": [{
            "label": "Số đơn",
            "data": tech_counts
        }]
    }

    db.close()

    return render_template(
        "admin_reports.html",
        monthly_data=monthly_data,
        type_data=type_data,
        tech_data=tech_data
    )

# static uploads serve (Flask static does it automatically but helper)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/delivery')
@role_required('delivery')
def delivery_dashboard():
    db = Session()
    try:
        # Nhân viên giao chỉ quan tâm đơn đã giao – nhận
        orders = db.query(WorkOrder).filter(
            WorkOrder.status.in_(["moi", "cho_giao_hang", "cho_nhan_lai"])
        ).order_by(WorkOrder.created_at.desc()).all()

        return render_template('delivery_orders.html', orders=orders)
    finally:
        db.close()

@app.route('/delivery/update/<int:order_id>', methods=['POST'])
@role_required('delivery')
def delivery_update(order_id):
    new_status = request.form.get('status')

    db = Session()
    try:
        order = db.query(WorkOrder).get(order_id)
        if not order:
            flash("Không tìm thấy đơn.", "danger")
            return redirect(url_for('delivery_dashboard'))

        old = order.status
        order.status = new_status

        hist = OrderHistory(
            order_id=order.id,
            old_status=old,
            new_status=new_status,
            changed_by=session['user_id'],
            note=f"Nhân viên giao cập nhật: {new_status}"
        )
        db.add(hist)
        db.commit()

        flash("Đã cập nhật trạng thái.")
    finally:
        db.close()

    return redirect(url_for('delivery_dashboard'))


@app.route('/admin/update/<int:order_id>', methods=['POST'])
@role_required('admin')
def admin_update_status(order_id):
    status = request.form.get('status')
    db = Session()
    try:
        order = db.query(WorkOrder).get(order_id)
        if order:
            order.status = status
            db.commit()
            flash('Admin đã cập nhật trạng thái.')
    finally:
        db.close()
    return redirect(url_for('admin_dashboard'))

def technician_available(db, tech_id, limit=10):
    active_orders = db.query(WorkOrder).filter(
        WorkOrder.technician_id == tech_id,
        WorkOrder.status != "da_hoan_thanh"     # chỉ tính đơn chưa hoàn thành
    ).count()

    return active_orders < limit



if __name__ == '__main__':
    app.run(debug=True)


