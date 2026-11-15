import json,hashlib,math
from src.services.expression import execute
from src.services.reference import expand_metric
VERSION='camp-aggregate-ratio-v2'
def ratio(n,d):
 if d==0:return None
 v=n/d
 if not math.isfinite(v) or abs(v)>1e15:raise ValueError('指标比值超出允许范围，请检查极小分母与口径')
 return v
def deps_diff(old_deps,new_deps):
 old={d['code']+':v'+str(d['version']):d for d in old_deps or []}
 new={d['code']+':v'+str(d['version']):d for d in new_deps or []}
 out=[]
 for k in sorted(set(old)|set(new)):
  if k not in old:out.append(dict(ref=k,change='新增依赖',before='—',after=new[k]['numerator']+' / ('+new[k]['denominator']+')'))
  elif k not in new:out.append(dict(ref=k,change='移除依赖',before=old[k]['numerator']+' / ('+old[k]['denominator']+')',after='—'))
  else:
   for f in ('numerator','denominator','numerator_mode','denominator_mode'):
    if old[k].get(f)!=new[k].get(f):out.append(dict(ref=k+'.'+f,change='依赖内容变更',before=old[k].get(f),after=new[k].get(f)))
 return out
def calculate(snapshot):
 m=snapshot['metric'];rows=snapshot['facts']
 if not rows:raise ValueError('所选日期没有班级日事实，请补充事实或扩大日期范围')
 deps=snapshot.get('deps') or []
 dep_map={(d['code'],d['version']):d for d in deps};dep_map[(m['code'],m['version'])]=m
 expanded=expand_metric(m,lambda c,v:dep_map.get((c,v)))
 n_tree=expanded['numerator']['tree'];d_tree=expanded['denominator']['tree']
 nr=[r for r in rows if m['numerator_mode']=='全部' or r['mode']==m['numerator_mode']]
 dr=[r for r in rows if m['denominator_mode']=='全部' or r['mode']==m['denominator_mode']]
 numerator=sum(execute(n_tree,r) for r in nr);denominator=sum(execute(d_tree,r) for r in dr)
 value=ratio(numerator,denominator)
 groups=[]
 for code in sorted({r['class_code'] for r in rows}):
  n=sum(execute(n_tree,r) for r in nr if r['class_code']==code);d=sum(execute(d_tree,r) for r in dr if r['class_code']==code)
  groups.append(dict(class_code=code,numerator=n,denominator=d,value=ratio(n,d)))
 baseline=snapshot.get('baseline');diff=None
 if baseline:
  old=baseline['result'];old_m=old['metric'];changes=[dict(field=k,before=old_m.get(k),after=m.get(k)) for k in ['version','name','numerator','denominator','numerator_mode','denominator_mode'] if old_m.get(k)!=m.get(k)]
  diff=dict(baseline_id=baseline['id'],previous_value=old['value'],current_value=value,delta=value-old['value'] if value is not None and old['value'] is not None else None,changed_fields=changes,changed_deps=deps_diff(old.get('deps'),deps) if 'deps' in old else None,same_date_window=snapshot['date_from']==baseline['date_from'] and snapshot['date_to']==baseline['date_to'],same_fact_checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==old['facts_checksum'])
 return dict(metric=m,rows=len(rows),numerator_rows=len(nr),denominator_rows=len(dr),numerator=numerator,denominator=denominator,value=value,undefined_reason='外层聚合分母为零' if value is None else '',groups=groups,expanded_numerator=expanded['numerator']['text'],expanded_denominator=expanded['denominator']['text'],deps=deps,ref_tree=expanded['tree'],diff=diff,facts_checksum=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),version=VERSION,method='先按日期和分子/分母各自授课方式过滤，再逐行计算白名单表达式，分别求和后相除；不是日比率简单平均。跨口径引用 @代码:v版本.numerator|denominator 已逐层展开为对方表达式，事实仍按引用处（本口径该侧）授课方式过滤。value为比值，页面乘100显示百分比。分母0保留null/undefined，不补零；过滤范围不同可能产生>100%或负比值，需人工核对口径。')
