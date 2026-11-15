from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.entities import Metric,Fact
from src.services.business import dump
from src.services.reference import expand_metric,RefError

def metric_lookup(s,own=None):
 """按(代码,版本)查口径；own为正在保存的口径自身，使自引用按新值解析。"""
 def look(code,version):
  if own and code==own['code'] and version==own['version']:return own
  r=s.query(Metric).filter_by(code=code,version=version).first()
  return dump(r) if r else None
 return look

def save_metric(s,data,i=None):
 r=s.get(Metric,i,with_for_update=True) if i else Metric()
 if not r:raise HTTPException(404,'口径版本不存在')
 if r.locked:raise HTTPException(409,'已签核口径不可覆盖，请建立新版本')
 for k,v in data.model_dump(mode='json').items():setattr(r,k,v)
 try:expand_metric(dump(r),metric_lookup(s,dump(r)))
 except RefError as e:raise HTTPException(400,str(e))
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'相同指标代码和版本已存在')
 return r

def save_fact(s,data,i=None):
 r=s.get(Fact,i) if i else Fact()
 if not r:raise HTTPException(404,'班级日事实不存在')
 for k,v in data.model_dump(mode='json').items():setattr(r,k,v)
 s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'相同班级与日期已有事实，请修订原记录')
 return r
