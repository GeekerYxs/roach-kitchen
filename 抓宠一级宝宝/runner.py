import sys,time,json,math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import re

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'batch_provision'))
from expwatch.__main__ import module_base, game_window_titles
from provisioner.memory import ProcessMemory
from provisioner.world import read_world, read_team, read_bag
from provisioner import native
from provisioner.game import Game, FIGHT_ESCAPE
from fighters import get_fighters

parser = argparse.ArgumentParser(description='单角色一级宝宝巡逻与捕捉；一角色启动一个进程')
parser.add_argument('--role', required=True, help='用于日志文件的角色标签')
parser.add_argument('--char-id', type=int, required=True, help='游戏内角色 ID，用于唯一识别进程')
parser.add_argument('--map', type=int, required=True, help='地图 ID')
parser.add_argument('--target', required=True, help='战斗中显示的目标名称，必须精确匹配')
parser.add_argument('--a', type=int, nargs=2, required=True, metavar=('X', 'Y'))
parser.add_argument('--b', type=int, nargs=2, required=True, metavar=('X', 'Y'))
parser.add_argument('--bait-id', type=int, default=8713, help='捕捉道具物品 ID')
parser.add_argument('--pet-item-id', type=int, required=True, help='目标宠物物品 ID，用于战后快照')
parser.add_argument('--attach', action='store_true', help='需要时注入仓库 DLL 并开启本地网络 tap')
args = parser.parse_args()
from provisioner import quizbot  # noqa: E402  user 2026-11-05: every line makes sure 启动答题器 runs (one per PC)
quizbot.ensure()
if not re.fullmatch(r'[\w\u4e00-\u9fff-]{1,40}', args.role):
    parser.error('角色标签只能包含字母、数字、中文、下划线及短横线')
role, CHAR, MAP, TARGET = args.role, args.char_id, args.map, args.target
ROOT = Path(__file__).resolve().parent / 'runtime'
ROOT.mkdir(parents=True, exist_ok=True)
LOG = ROOT / (role + '.jsonl')
STOP = ROOT / (role + '.stop')
if STOP.exists():
    raise RuntimeError(f'停止标记存在：{STOP}，请确认后移除')

matches=[]
for pid in game_window_titles():
 try:
  with ProcessMemory(pid,module_base(pid)) as probe:
   state=read_world(probe)
   if state and state.char_id==CHAR:matches.append(pid)
 except Exception:pass
if len(matches)!=1:raise RuntimeError(f'role process count invalid: {matches}')
PID=matches[0]
def get_bait(mem):
 bag=read_bag(mem) or ()
 return next((x for x in bag if x.item_id==args.bait_id and x.quantity>0),None)
def log(f,event,**fields):
 f.write(json.dumps(dict(time=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),event=event,**fields),ensure_ascii=False,default=str)+'\n');f.flush()
base=module_base(PID)
if not game_window_titles().get(PID):raise RuntimeError('role window missing')
mapping=None
if not native.has_dll(PID):
 if not args.attach:raise RuntimeError('目标进程未接入 DLL；使用 --attach 才会注入并启用网络 tap')
 sys.path.insert(0,str(REPO / 'batch_provision' / 'research' / 'shitu'))
 import attach_tap
 attach_tap.RUNTIME.mkdir(parents=True,exist_ok=True)
 mapping=attach_tap.attach(role,PID,attach_tap.fresh_dll())
st=native.read_status(PID)
if st.get('stage')!=8:raise RuntimeError('client not ready')
session=native.Session(PID,st['hwnd'],st['game_base'])
with ProcessMemory(PID,base) as mem,LOG.open('a',encoding='utf-8',buffering=1) as f:
 game=Game(session,mem)
 try:
  w=read_world(mem);team=read_team(mem)
  if mem.read(base+0x13310,15)!=bytes.fromhex('55 8b ec 83 e4 f8 8b 45 08 83 ec 0c 53 56 57'):raise RuntimeError('UseItemToFighter 签名不符')
  if not w or w.char_id!=CHAR or w.map_id!=MAP or (team and len(team.members)>1):raise RuntimeError('unexpected world state')
  bait=get_bait(mem)
  if not bait:raise RuntimeError('bait missing')
  points=[tuple(args.a),tuple(args.b)];idx=0;nav=0;count=0;inbattle=False;target=None;lastact=0;escape=False;escape_tries=0;attempts=0;stable=None;stable_at=0;started=0;last_roster=None;missing_since=None;had_target=False
  log(f,'started',role=role,pid=PID,char_id=CHAR,policy='until configured bait exhausted or stopped',points=points,bait_quantity_total=sum(x.quantity for x in (read_bag(mem) or ()) if x.item_id==args.bait_id),bait_slot=bait.slot,pet_items=[(x.slot,x.quantity) for x in (read_bag(mem) or ()) if x.item_id==args.pet_item_id])
  while not STOP.exists():
   now=time.monotonic();w=read_world(mem)
   if not w or w.char_id!=CHAR or w.map_id!=MAP:
    log(f,'guard_stop',reason='world or character changed',world=w);break
   bait_current=get_bait(mem)
   if not bait_current:
    game.cancel_navigation();log(f,'bait_exhausted',battles=count,in_battle=w.in_battle,target=target,attempts=attempts);break
   if w.in_battle:
    if not inbattle:
     inbattle=True;count+=1;started=now;target=None;lastact=0;escape=False;escape_tries=0;attempts=0;stable=None;stable_at=now;last_roster=None;missing_since=None;had_target=False;log(f,'battle_start',battle=count)
    enemies=[x for x in get_fighters(mem,base) if x.get('type')==1 and x.get('hp',0)>0 and not x.get('dead')]
    sig=tuple((x['slot'],x.get('name'),x.get('level')) for x in enemies)
    if sig!=stable:stable=sig;stable_at=now
    if sig!=last_roster and enemies:log(f,'roster',battle=count,enemies=enemies);last_roster=sig
    if target is None:
     candidates=[x for x in enemies if x.get('level')==1 and x.get('name')==TARGET]
     if candidates:
      target=dict(candidates[0]);had_target=True;missing_since=None;log(f,'target_locked',battle=count,target=target,candidates=candidates)
    if target is not None:
     cur=next((x for x in enemies if x['slot']==target['slot'] and x.get('name')==target['name'] and x.get('level')==1),None)
     if not cur:
      if missing_since is None:missing_since=now;log(f,'target_missing',battle=count,target=target,attempts=attempts,enemies=enemies)
      if now-missing_since>10:
       game.cancel_navigation();log(f,'target_missing_timeout',battle=count,target=target,attempts=attempts);break
      if now-missing_since>=1 and enemies and all(x.get('name') and x.get('level') is not None for x in enemies):
       log(f,'target_gone_continue',battle=count,target=target,attempts=attempts,enemies=enemies);target=None;missing_since=None;stable_at=now
      time.sleep(.1);continue
     missing_since=None
     if attempts>=50:
      game.cancel_navigation();log(f,'attempt_limit_pause',battle=count,target=target,attempts=attempts);break
     if w.my_sp is not None and now-lastact>=1:
      if w.my_sp>=3:
       ret=game.fight_command(7);lastact=now;log(f,'defend',battle=count,sp=w.my_sp,result=ret)
      elif w.my_sp>=1 and now-lastact>=3:
       bait=get_bait(mem)
       if not bait:
        game.cancel_navigation();log(f,'bait_missing_pause',battle=count,target=target,attempts=attempts);break
       ret=native.call(session,0x13310,cur['slot'],bait.slot);attempts+=1;lastact=now
       log(f,'bait_use',battle=count,attempt=attempts,target=cur,item_id=bait.item_id,slot=bait.slot,quantity_before=bait.quantity,sp=w.my_sp,result=ret)
    elif not escape and enemies and all(x.get('name') and x.get('level') is not None and not (x['level']==1 and x['name']==TARGET) for x in enemies) and now-stable_at>=1 and w.my_sp is not None and w.my_sp>=1:
     ret=game.fight_command(FIGHT_ESCAPE);escape=True;escape_tries=1;lastact=now;log(f,'escape_sent',battle=count,sp=w.my_sp,result=ret,tries=escape_tries)
    elif target is None and not had_target and not escape and now-started>20:
     game.cancel_navigation();log(f,'roster_or_sp_timeout',battle=count,enemies=enemies,sp=w.my_sp);break
    if escape and target is None and now-lastact>=4:
     if enemies and all(x.get('name') and x.get('level') is not None and not (x['level']==1 and x['name']==TARGET) for x in enemies) and w.my_sp is not None and w.my_sp>=1:
      ret=game.fight_command(FIGHT_ESCAPE);escape_tries+=1;lastact=now;log(f,'escape_retry',battle=count,sp=w.my_sp,result=ret,tries=escape_tries)
     elif now-lastact>15:
      lastact=now;log(f,'escape_wait',battle=count,tries=escape_tries,sp=w.my_sp,enemies=enemies)
   else:
    if inbattle:
     log(f,'battle_end',battle=count,target=target,attempts=attempts,escape_sent=escape,bait=[(x.item_id,x.slot,x.quantity) for x in (read_bag(mem) or ()) if x.item_id==args.bait_id],pet_items=[(x.slot,x.quantity) for x in (read_bag(mem) or ()) if x.item_id==args.pet_item_id],elapsed_seconds=round(now-started,2));inbattle=False
     if had_target:
      log(f,'target_battle_finished',battle=count,attempts=attempts,reason='capture outcome requires verification')
     elif not escape:
      game.cancel_navigation();log(f,'unexpected_battle_end_pause',battle=count);break
    pt=points[idx];dist=math.hypot(w.x-pt[0],w.y-pt[1])
    if now-nav>=2 and not w.moving:
     if dist<45:idx=1-idx;pt=points[idx]
     game.navigate(MAP,*pt);nav=now
   time.sleep(.1)
  if STOP.exists():game.cancel_navigation();log(f,'stopped',battles=count)
 except Exception as e:
  try: game.cancel_navigation()
  finally: log(f,'fatal',error=repr(e))
  raise
 finally:game.close()
