import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from src.config.database import db,Session
from src.models.entities import User,Metric,Fact,Snapshot,Audit
from src.schemas.business import Login,MetricInput,FactInput,RunInput,NoteInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.repository import save_metric,save_fact,metric_lookup
from src.services.reference import expand_metric,refs_of,RefError
from src.controllers import business as ensure
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/metrics')
def metrics(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Metric).order_by(Metric.code,Metric.version).all()]
@router.post('/metrics')
def create_metric(data:MetricInput,u=Depends(editor),s=Depends(db)):
 r=save_metric(s,data);audit(s,u,'建立口径 '+r.code+' v'+str(r.version));return dump(r)
@router.put('/metrics/{i}')
def edit_metric(i:int,data:MetricInput,u=Depends(editor),s=Depends(db)):
 r=save_metric(s,data,i);audit(s,u,'修订口径 '+str(i));return dump(r)
@router.get('/metrics/{i}/deps')
def metric_deps(i:int,u=Depends(current),s=Depends(db)):
 m=ensure.metric(s,i)
 used=[dict(id=x.id,code=x.code,version=x.version,from_part=part,to_part=rp) for x in s.query(Metric).order_by(Metric.code,Metric.version).all() for part in ('numerator','denominator') for rc,rv,rp,token in refs_of(getattr(x,part)) if rc==m.code and rv==m.version]
 try:expanded=expand_metric(dump(m),metric_lookup(s))
 except RefError as e:return dict(metric_id=i,ok=False,error=str(e),deps=[],tree=None,expanded=None,used_by=used)
 return dict(metric_id=i,ok=True,error='',deps=[{k:d[k] for k in ['id','code','version','name','numerator','denominator','numerator_mode','denominator_mode']} for d in expanded['deps']],tree=expanded['tree'],expanded={'numerator':expanded['numerator']['text'],'denominator':expanded['denominator']['text']},used_by=used)
@router.get('/facts')
def facts(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Fact).order_by(Fact.day.desc(),Fact.class_code).all()]
@router.post('/facts')
def create_fact(data:FactInput,u=Depends(editor),s=Depends(db)):
 r=save_fact(s,data);audit(s,u,'录入事实 '+str(r.id));return dump(r)
@router.put('/facts/{i}')
def edit_fact(i:int,data:FactInput,u=Depends(editor),s=Depends(db)):
 r=save_fact(s,data,i);audit(s,u,'修订事实 '+str(i));return dump(r)
@router.get('/snapshots')
def snapshots(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Snapshot).order_by(Snapshot.id.desc()).all()]
@router.post('/snapshots')
def run(data:RunInput,u=Depends(editor),s=Depends(db)):
 # 独立的REPEATABLE READ事务：整条依赖链与事实在同一完整时点冻结，并发修订要么全见要么全不见
 with Session(execution_options={'isolation_level':'REPEATABLE READ'}) as fs:
  m=ensure.metric(fs,data.metric_id)
  try:expanded=expand_metric(dump(m),metric_lookup(fs))
  except RefError as e:raise HTTPException(400,str(e))
  baseline=None
  if data.baseline_id:
   b=ensure.snapshot(fs,data.baseline_id)
   if b.state!='done':raise HTTPException(409,'仅成功快照可作为比较基线')
   if b.result['metric']['code']!=m.code:raise HTTPException(409,'只能比较同一指标代码的口径版本')
   baseline=dict(id=b.id,date_from=b.date_from,date_to=b.date_to,result={k:b.result[k] for k in ['metric','value','facts_checksum','deps'] if k in b.result})
  values=data.model_dump(mode='json');rows=[dump(f) for f in fs.query(Fact).filter(Fact.day>=values['date_from'],Fact.day<=values['date_to']).order_by(Fact.day,Fact.class_code).all()]
  frozen={'metric':dump(m),'deps':expanded['deps'],'facts':rows,'baseline':baseline,'date_from':values['date_from'],'date_to':values['date_to']}
 r=Snapshot(**values,result={'snapshot':frozen});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('camp:snapshots',r.id)
 except redis.RedisError:r.state='failed';r.error='队列不可用，请恢复后重新试算';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交试算 '+str(r.id)+'（冻结依赖 '+str(len(expanded['deps']))+' 个）');return dump(r)
@router.get('/snapshots/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure.snapshot(s,i))
@router.put('/snapshots/{i}/note')
def note(i:int,data:NoteInput,u=Depends(editor),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done' or r.approval=='approved':raise HTTPException(409,'仅成功且未签核快照可编辑意见')
 r.note=data.note;s.commit();audit(s,u,'起草签核意见 '+str(i));return dump(r)
@router.post('/snapshots/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done' or r.approval=='approved':raise HTTPException(409,'仅成功且未签核快照可签核')
 if r.result['value'] is None:raise HTTPException(409,'零分母undefined快照不能签核，请修正口径')
 if len(r.note)<8:raise HTTPException(409,'先填写至少8字业务解释')
 frozen_m=r.result['metric'];deps=r.result.get('deps') or []
 ids=sorted({r.metric_id}|{d['id'] for d in deps})
 # 整链按id升序加行锁：核对期间任何一环都不能被修订；任一环节过期则整体拒绝，全部一致才一起锁定
 rows=s.query(Metric).filter(Metric.id.in_(ids)).order_by(Metric.id).with_for_update().all()
 by_id={x.id:x for x in rows}
 m=by_id.get(r.metric_id)
 if not m:raise HTTPException(409,'口径已不存在，请重新试算')
 if any(getattr(m,k)!=v for k,v in frozen_m.items() if k not in ['locked']):raise HTTPException(409,'口径在试算后已变更，请用当前版本重新试算再签核')
 for d in deps:
  cur=by_id.get(d['id'])
  if not cur:raise HTTPException(409,'依赖口径 '+d['code']+' v'+str(d['version'])+' 已不存在，试算已过期，请重新试算再签核')
  changed=[k for k,v in d.items() if k not in ['id','locked'] and getattr(cur,k)!=v]
  if changed:raise HTTPException(409,'依赖口径 '+d['code']+' v'+str(d['version'])+' 的 '+('、'.join(changed))+' 在试算后已变更，试算已过期，请重新试算再签核')
 for x in rows:x.locked=True
 r.approval='approved';r.approved_by=u.email;s.commit();audit(s,u,'签核冻结 '+str(i)+'（整链 '+str(len(rows))+' 个口径一起锁定）');return dump(r)
@router.get('/snapshots/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure.snapshot(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功快照可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="camp-metric-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
