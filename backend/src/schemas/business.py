from pydantic import BaseModel,Field,field_validator
from typing import Literal
class Login(BaseModel):email:str;password:str
class ReaderInput(BaseModel):
 code:str=Field(min_length=1,max_length=60)
 weekly_reading:float=Field(ge=0,le=1000,allow_inf_nan=False)
 completion:float=Field(ge=0,le=1,allow_inf_nan=False)
 night_share:float=Field(ge=0,le=1,allow_inf_nan=False)
 note:str=Field(default='',max_length=1000)
class SegmentInput(BaseModel):
 name:str=Field(min_length=2,max_length=100)
 k:int=Field(default=3,ge=2,le=6)
 features:list[Literal['weekly_reading','completion','night_share']]=Field(default=['weekly_reading','completion','night_share'],min_length=2,max_length=3)
 @field_validator('features')
 @classmethod
 def unique(cls,v):
  if len(set(v))!=len(v):raise ValueError('特征不能重复')
  return v
class OutreachInput(BaseModel):
 segment_id:int=Field(gt=0)
 cluster_id:int=Field(ge=0,le=5)
 title:str=Field(min_length=2,max_length=100)
 note:str=Field(min_length=8,max_length=2000)
class SchedulePlanInput(BaseModel):
 outreach_id:int=Field(gt=0)
 target:int=Field(gt=0,le=10000)
class SchedulePreviewInput(BaseModel):
 week_start:str=Field(min_length=10,max_length=10)
 plans:list[SchedulePlanInput]=Field(min_length=1,max_length=50)
 @field_validator('week_start')
 @classmethod
 def monday(cls,v):
  from src.services.scheduling import monday_of
  try:monday_of(v)
  except ValueError as e:raise ValueError(str(e))
  return v
 @field_validator('plans')
 @classmethod
 def unique_outreach(cls,v):
  ids=[p.outreach_id for p in v]
  if len(set(ids))!=len(ids):raise ValueError('同一方案在一次排期中只能出现一次')
  return v
class ScheduleConfirmInput(BaseModel):
 preview_token:str=Field(min_length=16,max_length=64)
