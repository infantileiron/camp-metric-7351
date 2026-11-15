import ast,re
from src.services.expression import parse
# 引用记号：@代码:v版本.numerator 或 @代码:v版本.denominator，试算前逐层展开为对方表达式
REF_RE=re.compile(r'@([a-z][a-z0-9_]{1,39}):v([0-9]{1,5})\.(numerator|denominator)(?![a-z])')
PART_LABEL={'numerator':'分子','denominator':'分母'}
MAX_DEPTH=8
MAX_NODES=2000
class RefError(ValueError):pass
def refs_of(expression):
 return [(m.group(1),int(m.group(2)),m.group(3),m.group(0)) for m in REF_RE.finditer(expression or '')]
def strip_refs(expression):return REF_RE.sub('attended',expression or '')
def validate_syntax(expression):
 stripped=strip_refs(expression)
 if '@' in stripped:raise ValueError('引用记号格式应为 @代码:v版本.numerator 或 @代码:v版本.denominator')
 parse(stripped)
def frame_label(code,version,part):return '%s v%s %s'%(code,version,PART_LABEL[part])
def chain_label(chain):return ' → '.join(frame_label(c,v,p) for c,v,p in chain)
def _substitute(node,sub):
 if isinstance(node,ast.Expression):node.body=_substitute(node.body,sub);return node
 if isinstance(node,ast.Name):
  repl=sub.get(node.id)
  if repl is None:return node
  return repl.body if isinstance(repl,ast.Expression) else repl
 if isinstance(node,ast.BinOp):node.left=_substitute(node.left,sub);node.right=_substitute(node.right,sub);return node
 if isinstance(node,ast.UnaryOp):node.operand=_substitute(node.operand,sub);return node
 return node
def _expand_frame(metric,part,lookup,chain,cache,deps,edges):
 code,version=metric['code'],metric['version'];key=(code,version,part)
 if key in cache:return cache[key]
 expression=metric[part] or ''
 text=expression;sub={};size=0
 for i,(rc,rv,rp,token) in enumerate(refs_of(expression)):
  if (rc,rv,rp) in chain:raise RefError('口径引用成环：'+chain_label(chain+[(rc,rv,rp)]))
  if len(chain)>=MAX_DEPTH:raise RefError('引用层级超过%s层：%s'%(MAX_DEPTH,chain_label(chain+[(rc,rv,rp)])))
  target=lookup(rc,rv)
  if target is None:raise RefError('缺失引用：%s 不存在（来源链：%s）'%(frame_label(rc,rv,rp),chain_label(chain)))
  deps[(rc,rv)]=target;edges.append({'from':'%s:v%s.%s'%(code,version,part),'to':'%s:v%s.%s'%(rc,rv,rp)})
  sub_tree,sub_size=_expand_frame(target,rp,lookup,chain+[(rc,rv,rp)],cache,deps,edges)
  size+=sub_size
  if size>MAX_NODES:raise RefError('引用展开后超过%s个表达式节点（来源链：%s）'%(MAX_NODES,chain_label(chain)))
  sub['__ref%s__'%i]=sub_tree;text=text.replace(token,'__ref%s__'%i,1)
 if '@' in text:raise RefError('引用记号格式应为 @代码:v版本.numerator 或 @代码:v版本.denominator（来源链：%s）'%chain_label(chain))
 tree=parse(text,extra_names=tuple(sub))
 size+=len(list(ast.walk(tree)))
 if size>MAX_NODES:raise RefError('引用展开后超过%s个表达式节点（来源链：%s）'%(MAX_NODES,chain_label(chain)))
 origin=chain_label(chain)
 for node in ast.walk(tree):node.origin=origin
 tree=_substitute(tree,sub);cache[key]=(tree,size)
 return tree,size
def _part_tree(metric,part,lookup,stack):
 frame=(metric['code'],metric['version'],part)
 node={'label':frame_label(*frame),'code':metric['code'],'version':metric['version'],'part':part,'expression':metric[part],'refs':[]}
 if frame in stack:return node
 stack=stack|{frame}
 for rc,rv,rp,token in refs_of(metric[part]):
  target=lookup(rc,rv)
  if target is None:node['refs'].append({'label':frame_label(rc,rv,rp)+'（缺失）','code':rc,'version':rv,'part':rp,'missing':True,'refs':[]})
  else:node['refs'].append(_part_tree(target,rp,lookup,stack))
 return node
def expand_metric(metric,lookup):
 """逐层展开口径分子/分母中的跨口径引用。
 metric: 含 code/version/numerator/denominator 的dict；lookup(code,version)->dict或None。
 返回 {numerator:{tree,text,size}, denominator:{...}, deps:[...], edges:[...], tree:展示树}；
 缺失引用、成环、超层、超节点抛 RefError，消息含来源链。"""
 cache={};deps={};edges=[];out={}
 for part in ('numerator','denominator'):
  tree,size=_expand_frame(metric,part,lookup,[(metric['code'],metric['version'],part)],cache,deps,edges)
  out[part]={'tree':tree,'text':ast.unparse(tree),'size':size}
 out['deps']=[deps[k] for k in sorted(deps) if k!=(metric['code'],metric['version'])]
 out['edges']=edges
 out['tree']={'label':'%s v%s'%(metric['code'],metric['version']),'parts':[_part_tree(metric,'numerator',lookup,set()),_part_tree(metric,'denominator',lookup,set())]}
 return out
