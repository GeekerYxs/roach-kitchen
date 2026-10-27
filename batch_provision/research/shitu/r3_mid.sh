# Round 3, one team in 逍遥村 after 转职: sell junk (--safe), trials 1+2 (armor 3), PP鸡 to 通天塔, tower to 30.
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES. Run from research/shitu.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
python -X utf8 sell_tradable.py --safe "${APPS[@]}"
python -X utf8 trial_run.py --ask --armor 3 --master "$SHITU_MASTERS" "${APPS[@]}"
python -X utf8 pp_chain.py 通天塔 平静海岸2区
python -X utf8 tower28.py 30
echo R3_MID_DONE
