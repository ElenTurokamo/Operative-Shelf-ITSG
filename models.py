# models.py
import os
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from dotenv import load_dotenv

Base = declarative_base()
load_dotenv()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False) 
    it_code = Column(String(20), unique=True, nullable=False)  
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    
    last_msg_id = Column(BigInteger, nullable=True) 
    
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
    
    requests = relationship("Request", back_populates="user")

    def __repr__(self):
        return f"<User {self.it_code}>"


class Storage(Base):
    __tablename__ = 'storage'

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(100), nullable=False)
    item_name = Column(String(255), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    
    requests = relationship("Request", back_populates="item")

    def __repr__(self):
        return f"<Item {self.item_name} (Qty: {self.quantity})>"


class Request(Base):
    __tablename__ = 'requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    user_pk = Column(Integer, ForeignKey('users.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('storage.id'), nullable=False)
    
    req_count = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    
    is_approved = Column(Boolean, default=False)
    status = Column(String(20), default='pending', nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="requests")
    item = relationship("Storage", back_populates="requests")

    def __repr__(self):
        return f"<Request {self.id} by {self.user_pk}>"