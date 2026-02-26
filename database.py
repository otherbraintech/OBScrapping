import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
# SQLAlchemy requires 'postgresql://' instead of 'postgres://' sometimes
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    scrapes = relationship("ScrapeRequest", back_populates="user")

class ScrapeRequest(Base):
    __tablename__ = "scrape_requests"
    id = Column(String, primary_key=True)
    url = Column(String)
    network = Column(String, default="facebook")
    type = Column(String, default="reel")
    status = Column(String, default="pending")
    task_id = Column(String, unique=True, nullable=True)
    user_id = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="scrapes")
    result = relationship("ScrapeResult", back_populates="request", uselist=False)

class ScrapeResult(Base):
    __tablename__ = "scrape_results"
    id = Column(String, primary_key=True)
    content_type = Column(String, default="unknown")
    reactions = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    views = Column(Integer, default=0)
    error = Column(String, nullable=True)
    scraped_at = Column(DateTime, nullable=True)
    raw_data = Column(JSON, nullable=True)
    request_id = Column(String, ForeignKey("scrape_requests.id"), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    request = relationship("ScrapeRequest", back_populates="result")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
