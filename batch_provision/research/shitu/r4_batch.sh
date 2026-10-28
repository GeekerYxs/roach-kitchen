# r4_batch.sh TEAM BATCH (whole file parsed before it runs; SKIP / PAIRS from r4_env.sh): next batch for one master once its previous apprentices are 出师 (a master holds 4 at most).
# Makes the 4 roles (slot BATCH of that team's accounts cap21..cap36), arms their tap, restocks the master's 回城卷,
# then r4_sup.sh TEAM early (r4_early -> r4_mid -> r4_late with step retries). Logs: logs/<LOGID>_*.log
cd "$(dirname "$0")"
{
T=$1; export BATCH=$2
. ./r4_env.sh "$T"
pairs=($PAIRS)          # r4_env.sh: "capNN:亿万M" per kept apprentice (SKIP left out)
echo "$(date +%H:%M:%S) batch $BATCH team $T: ${pairs[*]}" >> "logs/${LOGID}_sup.log"
prev=$( (SKIP=; BATCH=$((BATCH - 1)); . ./r4_env.sh "$T"; echo "$SHITU_APPRENTICES") )   # skipped ones too
python -X utf8 -c "
import time, trial_run as t
from common import find_roles
from provisioner import native
for n in '$prev'.split(','):
    if n in find_roles((n,)):          # the previous batch logs in with the same accounts: close it first
        c = t.Client(n)
        st = native.read_status(c.pid)
        print(n, 'close', native.close(native.Session(c.pid, st['hwnd'], st['game_base'])))
time.sleep(3)
" >> "logs/${LOGID}_make.log" 2>&1
python -X utf8 make_apprentices.py "${pairs[@]}" >> "logs/${LOGID}_make.log" 2>&1 || { echo "$(date +%H:%M:%S) SUP_GIVEUP make -" >> "logs/${LOGID}_sup.log"; exit 1; }
python -X utf8 -c "
import trial_run as t
from provisioner import native
for n in '$SHITU_APPRENTICES'.split(','):
    c = t.Client(n)
    st = native.read_status(c.pid)
    native.arm(native.Session(c.pid, st['hwnd'], st['game_base']))
    print(n, 'armed')
" >> "logs/${LOGID}_make.log" 2>&1
python -X utf8 r4_util.py restock_master 100 >> "logs/${LOGID}_make.log" 2>&1
bash r4_sup.sh "$T" early
exit
}
