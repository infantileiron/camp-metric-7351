"""独立复算导出的试算快照，验证冻结依据可重算。

用法：python -m scripts.recalc_export camp-metric-<id>.json

只读取导出JSON内冻结的口径、整条依赖与班级日事实，重新逐层展开引用并计算，
与快照中的结果、分组、事实checksum及整体checksum逐项核对；全部一致退出码0，否则1。
"""
import sys,json
from src.services.analysis import calculate
COMPARE=['rows','numerator_rows','denominator_rows','numerator','denominator','value','facts_checksum','checksum']
def main(path):
 try:doc=json.load(open(path,encoding='utf-8'))
 except Exception as e:print('无法读取导出文件：',e);return 1
 res=doc.get('result') or {}
 snap=res.get('snapshot')
 if not snap:print('导出文件缺少冻结快照（口径/依赖/事实），无法独立复算');return 1
 print('快照 #%s · 口径 %s v%s · %s — %s'%(doc.get('id'),snap['metric']['code'],snap['metric']['version'],snap['date_from'],snap['date_to']))
 print('冻结事实 %s 条 · 冻结依赖 %s 个'%(len(snap['facts']),len(snap.get('deps') or [])))
 try:fresh=calculate(snap)
 except Exception as e:print('复算失败：',e);return 1
 bad=[]
 for k in COMPARE:
  if res.get(k)!=fresh.get(k):bad.append((k,res.get(k),fresh.get(k)))
 for k in ('expanded_numerator','expanded_denominator'):
  if k in res and res.get(k)!=fresh.get(k):bad.append((k,res.get(k),fresh.get(k)))
 g_old={g['class_code']:(g['numerator'],g['denominator'],g['value']) for g in res.get('groups',[])}
 g_new={g['class_code']:(g['numerator'],g['denominator'],g['value']) for g in fresh.get('groups',[])}
 if g_old!=g_new:bad.append(('groups',g_old,g_new))
 if bad:
  print('复算不一致：')
  for k,old,new in bad:print('  %s: 快照=%r 复算=%r'%(k,old,new))
  return 1
 print('复算一致：value=%r numerator=%r denominator=%r，分组、checksum全部吻合。'%(fresh['value'],fresh['numerator'],fresh['denominator']))
 return 0
if __name__=='__main__':
 if len(sys.argv)!=2:print('用法：python -m scripts.recalc_export <导出.json>');sys.exit(1)
 sys.exit(main(sys.argv[1]))
