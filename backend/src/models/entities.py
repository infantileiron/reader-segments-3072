from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,UniqueConstraint,Index
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Reader(Base):
 __tablename__='readers'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);weekly_reading=Column(Float);completion=Column(Float);night_share=Column(Float);note=Column(Text,default='')
class Segment(Base):
 __tablename__='segments'
 id=Column(Integer,primary_key=True);name=Column(String(100));k=Column(Integer);features=Column(JSON);state=Column(String(20),default='queued');result=Column(JSON);error=Column(Text,default='')
class Outreach(Base):
 __tablename__='outreaches'
 id=Column(Integer,primary_key=True);segment_id=Column(Integer,ForeignKey('segments.id'));cluster_id=Column(Integer);title=Column(String(100));note=Column(Text);members=Column(JSON);status=Column(String(20),default='draft')
class ScheduleBatch(Base):
 __tablename__='schedule_batches'
 id=Column(Integer,primary_key=True)
 week_start=Column(String(10),nullable=False)
 status=Column(String(20),default='preview')
 result=Column(JSON)
 preview_token=Column(String(64),unique=True)
 preview_expires_at=Column(String(40))
 confirmed_at=Column(String(40))
class ScheduleItem(Base):
 __tablename__='schedule_items'
 id=Column(Integer,primary_key=True)
 batch_id=Column(Integer,ForeignKey('schedule_batches.id'))
 week_start=Column(String(10),nullable=False)
 outreach_id=Column(Integer,ForeignKey('outreaches.id'))
 member_code=Column(String(60),nullable=False)
 __table_args__=(
  UniqueConstraint('week_start','member_code',name='uq_schedule_week_member'),
  Index('ix_schedule_batch','batch_id'),
 )
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
