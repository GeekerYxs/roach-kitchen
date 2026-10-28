# . r4_env.sh TEAM: export that team's SHITU_* and LOGID (shared by r4_run.sh / r4_sup.sh).
# BATCH (default 1) picks the apprentices: batch N, team a..d = 亿万(16(N-1)+1..4) .. 亿万(16(N-1)+13..16);
# batch N uses role slot N of the accounts cap21..cap36 (cap21 -> 亿万1, 亿万17, 亿万33, 亿万49).
B=${BATCH:-1}
case $1 in a) M=伏地魔1; k=0; G=50000 ;; b) M=伏地魔2; k=4; G=50000 ;; c) M=伏地魔3; k=8; G=50000 ;; d) M=伏地魔4; k=12; G=10000 ;; esac
o=$(( 16 * (B - 1) + k ))
A=亿万$((o+1)),亿万$((o+2)),亿万$((o+3)),亿万$((o+4))
# SKIP="亿万13 ..." leaves apprentices out (2026-10-28: 亿万13 lost the 181 日记 to a full bag, the tree never answered again)
ALL=$A
for x in $SKIP; do A=$(echo ",$A," | sed "s/,$x,/,/; s/^,//; s/,$//"); done
# PAIRS = "capNN:亿万M ..." for the apprentices kept: team slot i (0..3) is account cap(n0+i), role slot = BATCH
case $1 in a) n0=21 ;; b) n0=25 ;; c) n0=29 ;; d) n0=33 ;; esac
PAIRS=; i=0
for x in ${ALL//,/ }; do case ",$A," in *",$x,"*) PAIRS="$PAIRS cap$((n0 + i)):$x" ;; esac; i=$((i + 1)); done
PAIRS=${PAIRS# }
if [ "$B" = 1 ]; then LOGID=r4$1; STATE=state_r4$1.json; else LOGID=r4$1_b$B; STATE=state_r4$1_b$B.json; fi
export SHITU_STATE=$STATE SHITU_MASTERS=$M SHITU_APPRENTICES=$A SHITU_GOLD=$G SHITU_SCROLLS=20 LOGID PAIRS
