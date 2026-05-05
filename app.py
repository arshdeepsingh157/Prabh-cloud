"""
Smart Local Business Cloud CRM — Flask Backend
================================================
Tech: Flask + MySQL (AWS RDS compatible)
Auth: JWT
DB:   mysql+pymysql — configure DATABASE_URL in .env

Run (development):
    pip install flask flask-cors flask-sqlalchemy flask-jwt-extended pymysql python-dotenv
    # Create MySQL database first: CREATE DATABASE bizcrmdb;
    python app.py

Environment Variables (.env file):
    SECRET_KEY=your-secret-key
    JWT_SECRET_KEY=your-jwt-secret
    DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/bizcrmdb
    # AWS RDS:
    # DATABASE_URL=mysql+pymysql://admin:pass@your-rds-endpoint.rds.amazonaws.com:3306/bizcrmdb
    AWS_ACCESS_KEY_ID=your-key
    AWS_SECRET_ACCESS_KEY=your-secret
    AWS_REGION=ap-south-1
    S3_BUCKET=bizcrmapp-images
"""

import os
import json
import hashlib
import datetime
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
)

# ─────────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            static_folder=os.path.join(BASE_DIR, "static"),
            template_folder=os.path.join(BASE_DIR, "templates"))
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.config["SECRET_KEY"]                      = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
app.config["JWT_SECRET_KEY"]                  = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"]         = os.getenv("DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/bizcrmdb")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]  = False
app.config["JWT_ACCESS_TOKEN_EXPIRES"]        = datetime.timedelta(hours=12)
# Connection pool settings — essential for AWS RDS (handles dropped idle connections)
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 280,      # recycle connections before MySQL's wait_timeout (default 300s)
    "pool_pre_ping": True,    # test connection before use, reconnect if stale
    "pool_size": 5,
    "max_overflow": 10,
}

db  = SQLAlchemy(app)
jwt = JWTManager(app)

# ─────────────────────────────────────────────────────────
# DATABASE MODELS
# ─────────────────────────────────────────────────────────

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20),  default="staff")   # admin | staff
    created_at    = db.Column(db.DateTime,    default=datetime.datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = hashlib.sha256(pw.encode()).hexdigest()

    def check_password(self, pw):
        return self.password_hash == hashlib.sha256(pw.encode()).hexdigest()

    def to_dict(self):
        return {"id": self.id, "username": self.username,
                "email": self.email, "role": self.role,
                "created_at": str(self.created_at)}


class CustomerUser(db.Model):
    __tablename__ = "customer_users"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    phone         = db.Column(db.String(20),  default="")
    address       = db.Column(db.String(200), default="")
    customer_id   = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)
    joined        = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    customer      = db.relationship("Customer", backref=db.backref("portal_user", uselist=False))

    def set_password(self, pw):
        self.password_hash = hashlib.sha256(pw.encode()).hexdigest()

    def check_password(self, pw):
        return self.password_hash == hashlib.sha256(pw.encode()).hexdigest()

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email,
                "phone": self.phone, "address": self.address,
                "customer_id": self.customer_id, "joined": str(self.joined)}


class Customer(db.Model):
    __tablename__ = "customers"
    id            = db.Column(db.Integer, primary_key=True)
    fname         = db.Column(db.String(80),  nullable=False)
    lname         = db.Column(db.String(80),  nullable=False)
    email         = db.Column(db.String(120), unique=True)
    phone         = db.Column(db.String(20))
    address       = db.Column(db.String(200))
    total_spent   = db.Column(db.Float,   default=0.0)
    visits        = db.Column(db.Integer, default=0)
    joined        = db.Column(db.Date,    default=datetime.date.today)
    created_by    = db.Column(db.Integer, db.ForeignKey("users.id"))

    def loyalty_tier(self):
        if self.total_spent >= 15000: return "Gold"
        if self.total_spent >= 7000:  return "Silver"
        return "Bronze"

    def loyalty_score(self):
        return min(100, int(self.total_spent / 250))

    def to_dict(self):
        return {"id": self.id, "fname": self.fname, "lname": self.lname,
                "email": self.email, "phone": self.phone,
                "address": self.address, "total_spent": self.total_spent,
                "visits": self.visits, "joined": str(self.joined),
                "loyalty_tier": self.loyalty_tier(),
                "loyalty_score": self.loyalty_score()}


class Product(db.Model):
    __tablename__ = "products"
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), nullable=False)
    category    = db.Column(db.String(60),  nullable=False)
    price       = db.Column(db.Float,  nullable=False)
    stock       = db.Column(db.Integer, default=0)
    low_alert   = db.Column(db.Integer, default=10)
    image_url   = db.Column(db.String(500), default="📦")
    description = db.Column(db.Text)
    sold        = db.Column(db.Integer, default=0)
    created_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def is_low_stock(self):
        return self.stock <= self.low_alert

    def to_dict(self):
        return {"id": self.id, "name": self.name, "category": self.category,
                "price": self.price, "stock": self.stock,
                "low_alert": self.low_alert, "image_url": self.image_url,
                "description": self.description, "sold": self.sold,
                "is_low_stock": self.is_low_stock(),
                "created_at": str(self.created_at)}


class Sale(db.Model):
    __tablename__ = "sales"
    id          = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False)
    product_id  = db.Column(db.Integer, db.ForeignKey("products.id"),  nullable=True)
    qty         = db.Column(db.Integer, nullable=False)
    unit_price  = db.Column(db.Float,   nullable=False)
    total       = db.Column(db.Float,   nullable=False)
    method      = db.Column(db.String(30), default="Cash")
    sale_date   = db.Column(db.Date,    default=datetime.date.today)
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    customer    = db.relationship("Customer", backref="sales")
    product     = db.relationship("Product",  backref="sales")

    def to_dict(self):
        return {"id": self.id, "customer_id": self.customer_id,
                "product_id": self.product_id, "qty": self.qty,
                "unit_price": self.unit_price, "total": self.total,
                "method": self.method, "sale_date": str(self.sale_date),
                "customer_name": f"{self.customer.fname} {self.customer.lname}" if self.customer else "",
                "product_name": self.product.name if self.product else ""}


class InventoryLog(db.Model):
    __tablename__ = "inventory_logs"
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    action     = db.Column(db.String(30))  # restock | sale | adjustment
    qty_change = db.Column(db.Integer)
    note       = db.Column(db.String(200))
    logged_at  = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "product_id": self.product_id,
                "action": self.action, "qty_change": self.qty_change,
                "note": self.note, "logged_at": str(self.logged_at)}


class SupportTicket(db.Model):
    __tablename__ = "support_tickets"
    id               = db.Column(db.Integer, primary_key=True)
    customer_user_id = db.Column(db.Integer, db.ForeignKey("customer_users.id"), nullable=True)
    name             = db.Column(db.String(120))
    email            = db.Column(db.String(120))
    subject          = db.Column(db.String(200))
    message          = db.Column(db.Text)
    status           = db.Column(db.String(20), default="open")
    created_at       = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email,
                "subject": self.subject, "message": self.message,
                "status": self.status, "created_at": str(self.created_at)}


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def admin_required(fn):
    """Decorator: requires admin role in JWT."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("type") == "customer":
            return jsonify({"error": "Admin access required"}), 403
        uid  = int(get_jwt_identity())
        user = User.query.get(uid)
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper


def customer_required(fn):
    """Decorator: requires customer JWT."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get("type") != "customer":
            return jsonify({"error": "Customer access required"}), 403
        cu = CustomerUser.query.get(int(get_jwt_identity()))
        if not cu:
            return jsonify({"error": "Customer not found"}), 404
        return fn(*args, **kwargs)
    return wrapper


def success(data=None, msg="OK", code=200):
    return jsonify({"status": "success", "message": msg, "data": data}), code


def error(msg="Error", code=400):
    return jsonify({"status": "error", "message": msg}), code


# ─────────────────────────────────────────────────────────
# ROUTES — STATIC (serve the HTML frontend)
# ─────────────────────────────────────────────────────────

TMPL_DIR = os.path.join(BASE_DIR, "templates")

@app.route("/")
def index():
    return send_from_directory(TMPL_DIR, "index.html")

@app.route("/login")
def login_page():
    return send_from_directory(TMPL_DIR, "login.html")

@app.route("/customer")
def customer_portal():
    return send_from_directory(TMPL_DIR, "customer.html")


# ─────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
def register():
    """POST /api/auth/register  { username, email, password, role? }"""
    data = request.get_json() or {}
    if not data.get("username") or not data.get("email") or not data.get("password"):
        return error("username, email and password are required")

    if User.query.filter_by(email=data["email"]).first():
        return error("Email already registered", 409)

    user = User(
        username=data["username"].strip(),
        email=data["email"].strip().lower(),
        role=data.get("role", "staff")
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return success({"token": token, "user": user.to_dict()}, "Registered successfully", 201)


@app.route("/api/auth/login", methods=["POST"])
def login():
    """POST /api/auth/login  { email, password }"""
    data = request.get_json() or {}
    user = User.query.filter_by(email=data.get("email", "").lower()).first()

    if not user or not user.check_password(data.get("password", "")):
        return error("Invalid credentials", 401)

    token = create_access_token(identity=str(user.id), additional_claims={"type": "admin", "role": user.role})
    return success({"token": token, "user": user.to_dict()}, "Login successful")


@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def get_me():
    user = User.query.get(int(get_jwt_identity()))
    return success(user.to_dict())


# ─────────────────────────────────────────────────────────
# CUSTOMER PORTAL AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/customer/register", methods=["POST"])
def customer_register():
    """POST /api/customer/register  { name, email, password, phone?, address? }"""
    data = request.get_json() or {}
    if not data.get("name") or not data.get("email") or not data.get("password"):
        return error("name, email and password are required")

    email = data["email"].strip().lower()
    if CustomerUser.query.filter_by(email=email).first():
        return error("Email already registered", 409)

    # Create portal user
    cu = CustomerUser(
        name=data["name"].strip(),
        email=email,
        phone=data.get("phone", "").strip(),
        address=data.get("address", "").strip()
    )
    cu.set_password(data["password"])
    db.session.add(cu)
    db.session.flush()

    # Create corresponding Customer record for admin visibility
    parts = cu.name.split(" ", 1)
    fname = parts[0]
    lname = parts[1] if len(parts) > 1 else ""
    cust = Customer(fname=fname, lname=lname, email=email,
                    phone=cu.phone, address=cu.address)
    db.session.add(cust)
    db.session.flush()
    cu.customer_id = cust.id
    db.session.commit()

    token = create_access_token(identity=str(cu.id), additional_claims={"type": "customer"})
    return success({"token": token, "user": cu.to_dict()}, "Registered successfully", 201)


@app.route("/api/customer/login", methods=["POST"])
def customer_login():
    """POST /api/customer/login  { email, password }"""
    data = request.get_json() or {}
    cu = CustomerUser.query.filter_by(email=data.get("email", "").strip().lower()).first()

    if not cu or not cu.check_password(data.get("password", "")):
        return error("Invalid email or password", 401)

    token = create_access_token(identity=str(cu.id), additional_claims={"type": "customer"})
    return success({"token": token, "user": cu.to_dict()}, "Login successful")


@app.route("/api/customer/me", methods=["GET"])
@customer_required
def get_customer_me():
    cu = CustomerUser.query.get(int(get_jwt_identity()))
    data = cu.to_dict()
    if cu.customer:
        data["total_spent"] = cu.customer.total_spent
        data["loyalty_tier"] = cu.customer.loyalty_tier()
        data["loyalty_score"] = cu.customer.loyalty_score()
        data["visits"] = cu.customer.visits
    return success(data)


@app.route("/api/customer/me", methods=["PUT"])
@customer_required
def update_customer_me():
    cu   = CustomerUser.query.get(int(get_jwt_identity()))
    data = request.get_json() or {}
    if "name" in data and data["name"].strip():
        cu.name = data["name"].strip()
        if cu.customer:
            parts = cu.name.split(" ", 1)
            cu.customer.fname = parts[0]
            cu.customer.lname = parts[1] if len(parts) > 1 else ""
    if "phone" in data:
        cu.phone = data["phone"].strip()
        if cu.customer:
            cu.customer.phone = cu.phone
    if "address" in data:
        cu.address = data["address"].strip()
        if cu.customer:
            cu.customer.address = cu.address
    db.session.commit()
    return success(cu.to_dict(), "Profile updated")


@app.route("/api/customer/me", methods=["DELETE"])
@customer_required
def delete_customer_me():
    """DELETE requires { password } in body for verification."""
    cu   = CustomerUser.query.get(int(get_jwt_identity()))
    data = request.get_json() or {}
    if not cu.check_password(data.get("password", "")):
        return error("Incorrect password", 401)
    # Remove linked customer portal user but keep Customer record for audit
    if cu.customer:
        cu.customer.portal_user = None
    db.session.delete(cu)
    db.session.commit()
    return success(None, "Account deleted successfully")


@app.route("/api/customer/orders", methods=["GET"])
@customer_required
def get_customer_orders():
    cu = CustomerUser.query.get(int(get_jwt_identity()))
    if not cu or not cu.customer_id:
        return success({"orders": []})
    sales = Sale.query.filter_by(customer_id=cu.customer_id).order_by(Sale.sale_date.desc()).all()
    return success({"orders": [s.to_dict() for s in sales]})


@app.route("/api/customer/orders", methods=["POST"])
@customer_required
def create_customer_order():
    """POST /api/customer/orders { items:[{product_id,qty}], address, method }"""
    cu   = CustomerUser.query.get(int(get_jwt_identity()))
    data = request.get_json() or {}

    if not cu or not cu.customer_id:
        return error("Customer account not fully set up", 400)

    items   = data.get("items", [])
    address = data.get("address", "").strip()
    method  = data.get("method", "UPI")

    if not items:
        return error("No items in order")

    customer = Customer.query.get(cu.customer_id)
    created  = []
    total_order = 0

    for item in items:
        product = Product.query.get(item.get("product_id"))
        if not product:
            continue
        qty = max(1, int(item.get("qty", 1)))
        if product.stock < qty:
            return error(f"Insufficient stock for {product.name}. Available: {product.stock}", 422)

        total = product.price * qty
        sale  = Sale(
            customer_id=cu.customer_id,
            product_id=product.id,
            qty=qty,
            unit_price=product.price,
            total=total,
            method=method,
            sale_date=datetime.date.today()
        )
        db.session.add(sale)
        product.stock -= qty
        product.sold  += qty
        _log_inventory(product.id, "sale", -qty, f"Customer portal order")
        created.append(sale)
        total_order += total

    if customer:
        customer.total_spent += total_order
        customer.visits      += 1

    if customer and address:
        customer.address = address
        cu.address = address

    db.session.commit()
    return success({"orders": [s.to_dict() for s in created], "total": total_order}, "Order placed", 201)


# ─────────────────────────────────────────────────────────
# SUPPORT TICKETS
# ─────────────────────────────────────────────────────────

@app.route("/api/support/ticket", methods=["POST"])
@jwt_required()
def create_support_ticket():
    """POST /api/support/ticket { subject, message, name?, email? }"""
    data    = request.get_json() or {}
    claims  = get_jwt()
    cu_id   = None
    name    = data.get("name", "")
    email   = data.get("email", "")

    if claims.get("type") == "customer":
        cu = CustomerUser.query.get(int(get_jwt_identity()))
        if cu:
            cu_id  = cu.id
            name   = name or cu.name
            email  = email or cu.email

    if not data.get("subject") or not data.get("message"):
        return error("subject and message are required")

    ticket = SupportTicket(
        customer_user_id=cu_id,
        name=name,
        email=email,
        subject=data["subject"].strip(),
        message=data["message"].strip()
    )
    db.session.add(ticket)
    db.session.commit()
    return success(ticket.to_dict(), "Ticket submitted", 201)


# ─────────────────────────────────────────────────────────
# DEMO PAYMENT GATEWAY
# ─────────────────────────────────────────────────────────

@app.route("/api/payment/process", methods=["POST"])
@customer_required
def process_payment():
    """POST /api/payment/process { method, amount, card_last4?, upi_id? }
    Demo payment — always succeeds for non-zero amounts."""
    data   = request.get_json() or {}
    amount = float(data.get("amount", 0))
    method = data.get("method", "UPI")

    if amount <= 0:
        return error("Invalid payment amount")

    # Demo: simulate payment
    transaction_id = f"TXN{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}{int(get_jwt_identity())}"
    return success({
        "status":         "success",
        "transaction_id": transaction_id,
        "amount":         amount,
        "method":         method,
        "message":        f"Payment of ₹{amount:,.2f} via {method} successful"
    }, "Payment processed")


# ─────────────────────────────────────────────────────────
# ADMIN — CUSTOMER PURCHASE DETAILS
# ─────────────────────────────────────────────────────────

@app.route("/api/admin/customers/<int:cid>/purchases", methods=["GET"])
@admin_required
def get_customer_purchases(cid):
    c = Customer.query.get_or_404(cid)
    sales = Sale.query.filter_by(customer_id=cid).order_by(Sale.sale_date.desc()).all()
    return success({
        "customer":  c.to_dict(),
        "purchases": [s.to_dict() for s in sales],
        "total_spent": c.total_spent,
        "order_count": len(sales)
    })


# ─────────────────────────────────────────────────────────
# CUSTOMER ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/customers", methods=["GET"])
@jwt_required()
def get_customers():
    """GET /api/customers?q=name&tier=Gold&page=1&per_page=20"""
    q       = request.args.get("q", "")
    tier    = request.args.get("tier", "")
    page    = int(request.args.get("page", 1))
    per_pg  = int(request.args.get("per_page", 20))

    query = Customer.query
    if q:
        query = query.filter(
            (Customer.fname + " " + Customer.lname).ilike(f"%{q}%") |
            Customer.email.ilike(f"%{q}%") |
            Customer.phone.ilike(f"%{q}%")
        )

    customers = query.order_by(Customer.total_spent.desc()).paginate(
        page=page, per_page=per_pg, error_out=False
    )

    result = [c.to_dict() for c in customers.items]
    if tier:
        result = [c for c in result if c["loyalty_tier"] == tier]

    return success({
        "customers": result,
        "total": customers.total,
        "pages": customers.pages,
        "page": page
    })


@app.route("/api/customers/<int:cid>", methods=["GET"])
@jwt_required()
def get_customer(cid):
    c = Customer.query.get_or_404(cid)
    data = c.to_dict()
    data["sales"] = [s.to_dict() for s in c.sales]
    return success(data)


@app.route("/api/customers", methods=["POST"])
@jwt_required()
def create_customer():
    data = request.get_json() or {}
    if not data.get("fname") or not data.get("email"):
        return error("fname and email are required")

    if Customer.query.filter_by(email=data["email"]).first():
        return error("Customer with this email already exists", 409)

    c = Customer(
        fname=data["fname"].strip(),
        lname=data.get("lname", "").strip(),
        email=data["email"].strip().lower(),
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        created_by=int(get_jwt_identity())
    )
    db.session.add(c)
    db.session.commit()
    return success(c.to_dict(), "Customer added", 201)


@app.route("/api/customers/<int:cid>", methods=["PUT"])
@jwt_required()
def update_customer(cid):
    c    = Customer.query.get_or_404(cid)
    data = request.get_json() or {}
    for field in ("fname", "lname", "phone", "address"):
        if field in data:
            setattr(c, field, data[field])
    if "email" in data:
        c.email = data["email"].strip().lower()
    db.session.commit()
    return success(c.to_dict(), "Customer updated")


@app.route("/api/customers/<int:cid>", methods=["DELETE"])
@admin_required
def delete_customer(cid):
    c = Customer.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return success(None, "Customer deleted")


# ─────────────────────────────────────────────────────────
# PRODUCT ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/products", methods=["GET"])
@jwt_required()
def get_products():
    """GET /api/products?q=&category=&low_stock=true"""
    q         = request.args.get("q", "")
    category  = request.args.get("category", "")
    low_only  = request.args.get("low_stock") == "true"

    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%") | Product.description.ilike(f"%{q}%"))
    if category:
        query = query.filter(Product.category == category)

    products = query.order_by(Product.sold.desc()).all()
    if low_only:
        products = [p for p in products if p.is_low_stock()]

    return success({"products": [p.to_dict() for p in products]})


@app.route("/api/products/<int:pid>", methods=["GET"])
@jwt_required()
def get_product(pid):
    p = Product.query.get_or_404(pid)
    return success(p.to_dict())


@app.route("/api/products", methods=["POST"])
@jwt_required()
def create_product():
    data = request.get_json() or {}
    if not data.get("name") or not data.get("price"):
        return error("name and price are required")

    p = Product(
        name=data["name"].strip(),
        category=data.get("category", "Other"),
        price=float(data["price"]),
        stock=int(data.get("stock", 0)),
        low_alert=int(data.get("low_alert", 10)),
        image_url=data.get("image_url", "📦"),
        description=data.get("description", "")
    )
    db.session.add(p)
    db.session.commit()

    _log_inventory(p.id, "initial_stock", p.stock, "Product created")
    return success(p.to_dict(), "Product added", 201)


@app.route("/api/products/<int:pid>", methods=["PUT"])
@jwt_required()
def update_product(pid):
    p    = Product.query.get_or_404(pid)
    data = request.get_json() or {}

    old_stock = p.stock
    for field in ("name", "category", "price", "stock", "low_alert", "image_url", "description"):
        if field in data:
            setattr(p, field, data[field])

    if p.stock != old_stock:
        _log_inventory(p.id, "adjustment", p.stock - old_stock, "Manual stock update")

    db.session.commit()
    return success(p.to_dict(), "Product updated")


@app.route("/api/products/<int:pid>/restock", methods=["POST"])
@jwt_required()
def restock_product(pid):
    p    = Product.query.get_or_404(pid)
    data = request.get_json() or {}
    qty  = int(data.get("qty", 50))
    p.stock += qty
    _log_inventory(p.id, "restock", qty, data.get("note", "Restock"))
    db.session.commit()
    return success(p.to_dict(), f"Restocked {qty} units")


@app.route("/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def delete_product(pid):
    p = Product.query.get_or_404(pid)
    InventoryLog.query.filter_by(product_id=pid).delete()
    Sale.query.filter_by(product_id=pid).update({"product_id": None})
    db.session.flush()
    db.session.delete(p)
    db.session.commit()
    return success(None, "Product deleted")


def _log_inventory(product_id, action, qty_change, note=""):
    log = InventoryLog(product_id=product_id, action=action, qty_change=qty_change, note=note)
    db.session.add(log)


# ─────────────────────────────────────────────────────────
# SALES ENDPOINTS
# ─────────────────────────────────────────────────────────

@app.route("/api/sales", methods=["GET"])
@jwt_required()
def get_sales():
    """GET /api/sales?from=2025-01-01&to=2025-12-31&customer_id=&page=1"""
    from_d  = request.args.get("from")
    to_d    = request.args.get("to")
    cust_id = request.args.get("customer_id")
    page    = int(request.args.get("page", 1))
    per_pg  = int(request.args.get("per_page", 30))

    query = Sale.query
    if from_d:
        query = query.filter(Sale.sale_date >= from_d)
    if to_d:
        query = query.filter(Sale.sale_date <= to_d)
    if cust_id:
        query = query.filter(Sale.customer_id == int(cust_id))

    sales = query.order_by(Sale.sale_date.desc()).paginate(
        page=page, per_page=per_pg, error_out=False
    )
    total_rev = db.session.query(db.func.sum(Sale.total)).scalar() or 0

    return success({
        "sales": [s.to_dict() for s in sales.items],
        "total_revenue": total_rev,
        "total_orders": Sale.query.count(),
        "pages": sales.pages,
        "page": page
    })


@app.route("/api/sales", methods=["POST"])
@jwt_required()
def create_sale():
    """POST /api/sales { customer_id, product_id, qty, method, sale_date? }"""
    data = request.get_json() or {}
    if not data.get("customer_id") or not data.get("product_id") or not data.get("qty"):
        return error("customer_id, product_id, qty are required")

    product = Product.query.get(data["product_id"])
    if not product:
        return error("Product not found", 404)

    qty = int(data["qty"])
    if product.stock < qty:
        return error(f"Insufficient stock. Available: {product.stock}", 422)

    customer = Customer.query.get(data["customer_id"])
    if not customer:
        return error("Customer not found", 404)

    total = product.price * qty

    sale = Sale(
        customer_id=customer.id,
        product_id=product.id,
        qty=qty,
        unit_price=product.price,
        total=total,
        method=data.get("method", "Cash"),
        sale_date=data.get("sale_date") or datetime.date.today(),
        created_by=int(get_jwt_identity())
    )
    db.session.add(sale)

    # Update stock and sold count
    product.stock -= qty
    product.sold  += qty

    # Update customer spend
    customer.total_spent += total
    customer.visits      += 1

    # Inventory log
    _log_inventory(product.id, "sale", -qty, f"Sale #{sale.id}")
    db.session.commit()

    response_data = sale.to_dict()
    response_data["low_stock_alert"] = product.is_low_stock()
    return success(response_data, "Sale recorded", 201)


@app.route("/api/sales/<int:sid>", methods=["GET"])
@jwt_required()
def get_sale(sid):
    s = Sale.query.get_or_404(sid)
    return success(s.to_dict())


# ─────────────────────────────────────────────────────────
# INVENTORY LOGS
# ─────────────────────────────────────────────────────────

@app.route("/api/inventory/logs", methods=["GET"])
@jwt_required()
def get_inventory_logs():
    pid  = request.args.get("product_id")
    query = InventoryLog.query
    if pid:
        query = query.filter_by(product_id=int(pid))
    logs = query.order_by(InventoryLog.logged_at.desc()).limit(100).all()
    return success({"logs": [l.to_dict() for l in logs]})


# ─────────────────────────────────────────────────────────
# DASHBOARD STATS
# ─────────────────────────────────────────────────────────

@app.route("/api/dashboard/stats", methods=["GET"])
@jwt_required()
def dashboard_stats():
    """Returns aggregated stats for the dashboard overview."""
    total_rev   = db.session.query(db.func.sum(Sale.total)).scalar() or 0
    total_orders = Sale.query.count()
    total_cust  = Customer.query.count()
    low_stock   = Product.query.filter(Product.stock <= Product.low_alert).count()

    # Monthly revenue (last 6 months)
    today  = datetime.date.today()
    months = []
    for i in range(5, -1, -1):
        m = today.replace(day=1) - datetime.timedelta(days=i*30)
        label = m.strftime("%b")
        start = m.replace(day=1)
        if m.month == 12:
            end = m.replace(year=m.year+1, month=1, day=1)
        else:
            end = m.replace(month=m.month+1, day=1)
        rev = db.session.query(
            db.func.sum(Sale.total)
        ).filter(Sale.sale_date >= start, Sale.sale_date < end).scalar() or 0
        months.append({"month": label, "revenue": float(rev)})

    # Top products
    top_products = db.session.query(
        Product.name, Product.sold, Product.category
    ).order_by(Product.sold.desc()).limit(5).all()

    # Day of week sales
    dow_sales = {}
    all_sales = Sale.query.all()
    for s in all_sales:
        day = s.sale_date.strftime("%a")
        dow_sales[day] = dow_sales.get(day, 0) + s.total

    return success({
        "total_revenue":  float(total_rev),
        "total_orders":   total_orders,
        "total_customers": total_cust,
        "low_stock_count": low_stock,
        "monthly_revenue": months,
        "top_products":   [{"name": p[0], "sold": p[1], "category": p[2]} for p in top_products],
        "dow_sales":      dow_sales
    })


# ─────────────────────────────────────────────────────────
# AI INSIGHTS ENDPOINT (calls Lambda in production)
# ─────────────────────────────────────────────────────────

@app.route("/api/insights", methods=["GET"])
@jwt_required()
def get_insights():
    """
    In production: invoke AWS Lambda function 'bizcrmAIInsights' via boto3.
    Here we compute insights locally for demo purposes.
    """
    products = Product.query.all()
    sales    = Sale.query.all()
    customers = Customer.query.all()

    if not products or not sales:
        return success({"insights": [], "forecast": []})

    # Best seller
    top_sold = max(products, key=lambda p: p.sold)

    # Declining product
    declining = min(products, key=lambda p: p.sold)

    # Best day
    day_totals = {}
    for s in sales:
        day = s.sale_date.strftime("%A")
        day_totals[day] = day_totals.get(day, 0) + s.total
    best_day = max(day_totals, key=day_totals.get) if day_totals else "—"

    # Restock list
    low_products = [p.name for p in products if p.is_low_stock()]

    # Top customer
    top_cust = max(customers, key=lambda c: c.total_spent) if customers else None

    # Average order value
    total_rev = sum(s.total for s in sales)
    avg_order = total_rev / len(sales) if sales else 0

    insights = [
        {"icon": "🏆", "title": "Best Selling Product",
         "text": f"{top_sold.name} leads with {top_sold.sold} units sold. Increase its stock.",
         "category": "product"},
        {"icon": "📉", "title": "Declining Product",
         "text": f"{declining.name} has the lowest sales ({declining.sold} units). Consider a promotion.",
         "category": "product"},
        {"icon": "📅", "title": "Peak Sales Day",
         "text": f"Your best sales day is {best_day}. Maximise promotions on this day.",
         "category": "sales"},
        {"icon": "📦", "title": "Restock Required",
         "text": f"Urgently restock: {', '.join(low_products) if low_products else 'None — all stocked!'}",
         "category": "inventory"},
        {"icon": "👑", "title": "Top Customer",
         "text": f"{top_cust.fname} {top_cust.lname} has spent ₹{top_cust.total_spent:,.0f}. Send a loyalty reward!" if top_cust else "No customers yet.",
         "category": "customer"},
        {"icon": "💡", "title": "Avg Order Value",
         "text": f"Average order is ₹{avg_order:,.0f}. Try upselling to increase this by 15-20%.",
         "category": "sales"},
    ]

    # Simple linear forecast (last 6 months trend)
    forecast = [
        {"month": "Month 1", "projected": round(total_rev * 1.05)},
        {"month": "Month 2", "projected": round(total_rev * 1.08)},
        {"month": "Month 3", "projected": round(total_rev * 1.12)},
        {"month": "Month 4", "projected": round(total_rev * 1.15)},
        {"month": "Month 5", "projected": round(total_rev * 1.18)},
        {"month": "Month 6", "projected": round(total_rev * 1.22)},
    ]

    return success({"insights": insights, "forecast": forecast})


# ─────────────────────────────────────────────────────────
# CHATBOT ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@jwt_required()
def chat():
    """POST /api/chat { message: "Which product sold the most?" }"""
    data    = request.get_json() or {}
    message = data.get("message", "").lower().strip()

    if not message:
        return error("message is required")

    products  = Product.query.all()
    sales_all = Sale.query.all()
    customers = Customer.query.all()

    total_rev = sum(s.total for s in sales_all)
    top_sold  = max(products, key=lambda p: p.sold) if products else None
    low_stock = [p for p in products if p.is_low_stock()]
    top_cust  = max(customers, key=lambda c: c.total_spent) if customers else None

    day_totals = {}
    for s in sales_all:
        day = s.sale_date.strftime("%A")
        day_totals[day] = day_totals.get(day, 0) + s.total
    best_day = max(day_totals, key=day_totals.get) if day_totals else "—"

    response = "I can help with product sales, stock levels, customer info, and revenue insights."

    if any(k in message for k in ["top sell", "best sell", "most sell", "popular"]):
        response = f"🏆 {top_sold.name} is your top seller with {top_sold.sold} units sold." if top_sold else "No sales data yet."

    elif any(k in message for k in ["low stock", "restock", "running out"]):
        if low_stock:
            names = ", ".join(p.name for p in low_stock[:5])
            response = f"⚠️ {len(low_stock)} item(s) need restocking: {names}."
        else:
            response = "✅ All products are well stocked!"

    elif any(k in message for k in ["customer", "who buy", "loyal"]):
        response = f"👑 Top customer: {top_cust.fname} {top_cust.lname} — spent ₹{top_cust.total_spent:,.0f}." if top_cust else "No customers yet."

    elif any(k in message for k in ["revenue", "sales", "earn", "income", "money"]):
        avg = total_rev / len(sales_all) if sales_all else 0
        response = f"💰 Total revenue: ₹{total_rev:,.0f} across {len(sales_all)} orders. Avg order: ₹{avg:,.0f}."

    elif any(k in message for k in ["best day", "day of week", "peak day"]):
        response = f"📅 Your peak sales day is {best_day}. Plan promotions accordingly!"

    elif any(k in message for k in ["hello", "hi", "hey", "help"]):
        response = "👋 Hi! Ask me about top products, low stock, customers, revenue, or best sales days."

    return success({"response": response})


# ─────────────────────────────────────────────────────────
# REPORTS / EXPORT ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/reports/sales", methods=["GET"])
@jwt_required()
def export_sales_report():
    """Returns JSON report data; frontend handles CSV conversion."""
    sales = Sale.query.order_by(Sale.sale_date.desc()).all()
    return success({"report": [s.to_dict() for s in sales], "generated_at": str(datetime.datetime.utcnow())})


@app.route("/api/reports/inventory", methods=["GET"])
@jwt_required()
def export_inventory_report():
    products = Product.query.all()
    return success({"report": [p.to_dict() for p in products], "generated_at": str(datetime.datetime.utcnow())})


# ─────────────────────────────────────────────────────────
# NOTIFICATIONS ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    notifs = []
    low_stock = Product.query.filter(Product.stock <= Product.low_alert).all()
    for p in low_stock:
        notifs.append({"type": "red", "text": f"{p.name} is low on stock ({p.stock} left)", "time": "Now"})

    # High value customer milestone
    gold_customers = [c for c in Customer.query.all() if c.loyalty_tier() == "Gold"]
    if gold_customers:
        notifs.append({"type": "green", "text": f"{len(gold_customers)} Gold tier customer(s) this month!", "time": "Today"})

    return success({"notifications": notifs})


# ─────────────────────────────────────────────────────────
# SEARCH ENDPOINT
# ─────────────────────────────────────────────────────────

@app.route("/api/search", methods=["GET"])
@jwt_required()
def global_search():
    """GET /api/search?q=jeans"""
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return error("Query must be at least 2 characters")

    products  = Product.query.filter(Product.name.ilike(f"%{q}%")).limit(5).all()
    customers = Customer.query.filter(
        (Customer.fname + " " + Customer.lname).ilike(f"%{q}%") |
        Customer.email.ilike(f"%{q}%")
    ).limit(5).all()

    return success({
        "products":  [p.to_dict() for p in products],
        "customers": [c.to_dict() for c in customers]
    })


# ─────────────────────────────────────────────────────────
# AWS S3 PRESIGNED URL (for product image upload)
# ─────────────────────────────────────────────────────────

@app.route("/api/s3/presign", methods=["POST"])
@jwt_required()
def get_presigned_url():
    """
    POST /api/s3/presign { filename: "product.jpg", content_type: "image/jpeg" }
    Returns a presigned S3 URL for direct browser upload.
    Requires: pip install boto3
    """
    try:
        import boto3
        from botocore.exceptions import NoCredentialsError

        data         = request.get_json() or {}
        filename     = data.get("filename", "upload.jpg")
        content_type = data.get("content_type", "image/jpeg")
        bucket       = os.getenv("S3_BUCKET", "bizcrmapp-images")
        region       = os.getenv("AWS_REGION", "ap-south-1")

        s3 = boto3.client("s3", region_name=region)
        key = f"products/{datetime.datetime.utcnow().timestamp()}_{filename}"

        url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=300
        )
        public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        return success({"upload_url": url, "public_url": public_url})

    except ImportError:
        return error("boto3 not installed. Run: pip install boto3")
    except Exception as e:
        return error(str(e), 500)


# ─────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return success({"status": "healthy", "version": "1.0.0",
                    "timestamp": str(datetime.datetime.utcnow())})


# ─────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    print("""
╔══════════════════════════════════════════════════════╗
║  🏪  BizCRM — Smart Local Business CRM              ║
║  Flask backend running on http://localhost:5000      ║
╠══════════════════════════════════════════════════════╣
║  API Endpoints:                                      ║
║    POST /api/auth/register                           ║
║    POST /api/auth/login                              ║
║    GET  /api/customers                               ║
║    GET  /api/products                                ║
║    POST /api/sales                                   ║
║    GET  /api/insights                                ║
║    POST /api/chat                                    ║
║    GET  /api/dashboard/stats                         ║
║    GET  /api/health                                  ║
╚══════════════════════════════════════════════════════╝
    """)

    app.run(debug=True, host="0.0.0.0", port=5000)
