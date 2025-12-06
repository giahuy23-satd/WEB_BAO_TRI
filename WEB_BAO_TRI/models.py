# models.py
from sqlalchemy import create_engine, Column, Integer, String, Text, Enum, ForeignKey, TIMESTAMP
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func
from werkzeug.security import generate_password_hash
import os

Base = declarative_base()

class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    full_name = Column(String(150))
    email = Column(String(150), unique=True)
    phone = Column(String(50))
    password_hash = Column(String(255))
    role = Column(Enum('customer','technician','admin', name='user_roles'), default='customer')
    created_at = Column(TIMESTAMP, server_default=func.now())

class Customer(Base):
    __tablename__ = 'customer'
    id = Column(Integer, primary_key=True)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(50))
    email = Column(String(150))
    address = Column(String(255))
    created_at = Column(TIMESTAMP, server_default=func.now())

class WorkOrder(Base):
    __tablename__ = 'work_order'
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customer.id'), nullable=False)
    technician_id = Column(Integer, ForeignKey('user.id'), nullable=True)
    order_type = Column(Enum('baotri','suachua', name='order_type'), nullable=False)
    priority = Column(Enum('low','normal','high', name='priority_type'), default='normal')
    description = Column(Text)
    status = Column(Enum('moi','dang_xu_ly','da_hoan_thanh', name='status_type'), default='moi')
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())

    customer = relationship('Customer', backref='orders')
    technician = relationship('User', foreign_keys=[technician_id])

class OrderImage(Base):
    __tablename__ = 'order_images'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('work_order.id'), nullable=False)
    file_path = Column(String(255), nullable=False)
    uploaded_by = Column(Integer, ForeignKey('user.id'))
    created_at = Column(TIMESTAMP, server_default=func.now())

class OrderHistory(Base):
    __tablename__ = 'order_history'
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey('work_order.id'), nullable=False)
    old_status = Column(Enum('moi','dang_xu_ly','da_hoan_thanh', name='hist_old_status'), nullable=True)
    new_status = Column(Enum('moi','dang_xu_ly','da_hoan_thanh', name='hist_new_status'), nullable=False)
    changed_by = Column(Integer, ForeignKey('user.id'))
    note = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())

# Database engine
def get_engine():
    # Update connection as needed
    return create_engine("mysql+pymysql://root:1234@127.0.0.1/quanlybaotri?charset=utf8mb4", echo=False)

def create_all():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine

def create_default_admin_if_not_exists(session):
    admin_email = "admin@local"
    admin = session.query(User).filter(User.email == admin_email).first()
    if not admin:
        pwd = "Admin@123"  # default password — change ASAP
        admin = User(full_name="Super Admin", email=admin_email, password_hash=generate_password_hash(pwd), role='admin')
        session.add(admin)
        session.commit()
        print(f"Default admin created: {admin_email} / {pwd}")


