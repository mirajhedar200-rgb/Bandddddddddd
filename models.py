from sqlalchemy import Column, Integer, BigInteger, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True, index=True)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    referrals_count = Column(Integer, default=0)
    invited_by = Column(BigInteger, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

class ForcedChannel(Base):
    __tablename__ = "forced_channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_username = Column(String, unique=True, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
