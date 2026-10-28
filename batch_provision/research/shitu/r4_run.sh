# Round 4 launcher: r4_run.sh <team a|b|c|d> <script>  -> env for that team (r4_env.sh, BATCH), log appended to
# logs/<LOGID>_<script>.log
T=$1; S=$2
cd "$(dirname "$0")"
. ./r4_env.sh "$T"
bash "$S" >> "logs/${LOGID}_${S%.sh}.log" 2>&1
echo "team $T $S exit $?"
