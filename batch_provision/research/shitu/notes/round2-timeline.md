# 师徒第二轮（自动，无人值守）2026-10-27 03:25 起 — 进度流水

- 03:25 基线：伏地魔1 gold 2257437，伏地魔2 2221365，都 70 级在 map 1，224 都是 steps=(2,1)。
- 03:26:43–03:27:30 建号 + 出新手村 47 s：mvp01–03 槽 2 = 百万1 222155 / 百万2 222156 / 百万3 222157
  （槽 1 仍显示 十万N 31 级 = 03:04 删除待释放的；删掉的角色还留在列表里，新号落在槽 2，没等）。
- 名字通过环境变量 SHITU_APPRENTICES=百万1,百万2,百万3 传给所有脚本（common.APPRENTICES）。
- 03:28:38–03:28:45 拜师 3 个，7 s，全部一次成功。**已验证：03:05 解除 3 个徒弟后，师傅立刻能再收新徒弟**（0x4337 第 5–7 字节 0001/1b1d/0002）。
- 03:28:57–03:31:54 古井 2→10，11 场，3.0 分（吃 2 地瓜+酒池+肉林）。
- 03:32:00–03:34:21 supply_go：**两次失败后修好**——① 古井里刚好遇怪，交易丢了；② 0x46ff「玩家距离您太远」：well10 结束时队伍拉成一列，伏地魔1 离 百万1 230 px。supply_go.calm() 现在先等战斗结束，距离 >80 px 就离队走过去，交易没到账重试一次。之后 10 卷 + 5 万 ×3、回城、PP鸡到 81 约 55 s。
- 03:34:26–03:34:32 pp_unlock 6 s（3 条「认可你了」）。
- 03:34:38–03:39:47 轮回之城 10→15，21 场 5.1 分。
- 03:39:5x–04:00:21 迷宫 15→19（暗影迷城 8.0 分）→23（八阵图）→大个王，81 场 20.3 分。
- 04:00:38–04:00:41 飞鞋 5 人（新脚本 shoe_dagewang.py），3 s。
- 04:00:50 全员回城卷；04:01:00–04:01:26 接转职任务 24（3 个号依次走去就职所，~9 s/个）。
- 04:01:34–04:03:43 拳手 6 场 1.6 分。**quanshou.py 现在读录包 0x46ff「已经杀死了N个75Kg级拳手」自动停**（去掉颜色码），不再靠任务树；maze_train 加了通用 done_when 钩子。
- 04:03:52–04:03:58 交拳手；04:04:0x–04:04:48 梦幻岛转战士（3 个 ~45 s）；04:05:02–04:05:09 NPC 308 交任务 94。
- 04:05:16–04:06:45 考验一、二，3 个号 15 题全在题库，护甲 3。**考验一这次 +2000（上一轮 25 级时 +2690），考验二 +20000**。
- 04:06:59–04:07:18 pp_chain 到通天塔路口（各 -500）；04:07:39 tower28.py 现在自己点通天塔门 952 选一区。
- 04:07:41–04:40:18 通天塔一区 23→30，111 场 **32.7 分**（~5 分/级；上一轮 23→30 有一部分是在古洞采花时升的）。
- 04:40:30–04:41:14 take224 3 个徒弟单独接（各 ~14 s），伏地魔1/2 只飞鞋 + 传到无尽2路口（不重接，保留 (2,1)）；04:41:47–04:43:01 进洞。
- **04:43–04:48 采花失败 #1**：伏地魔1 点每朵花都只有「离开」——**采集选项只给任务 224 停在第 1 步的人**，伏地魔1 已是 (2,1)。最后寻路到 4187 (2887,3330) 时走出洞口到 141，gather 停。
  → 队长改成徒弟：lunhui15 新增 SHITU_LEADER 环境变量 + CASTERS（施法永远是伏地魔1/2）+ MEMBERS。花/石 items.csv 不可交易，所以采花的徒弟也要当打蛇的队长。
- **04:50–04:57 采花失败 #2**：百万1「物品栏已满！」——3 个徒弟背包都 40/40（这轮转职前没卖过杂物；伏地魔1/2 78/80、80/80）。
  → 04:58 全员回城卷，sell_tradable.py --junk（新开关：不脱武器、留回城卷）每人 34 格一次卖完，+4050/+4364/+4604。
  → 回洞：飞鞋 04:40 用过（1 小时冷却），改走 PP鸡 1→81→「龙之都690」→ map 20 (4050,303)，再走去 141 进洞。**PP 菜单按队长解锁的目的地显示**：百万1 当队长时 81 的 PP鸡只给 逍遥村/乌龙村，伏地魔1 当队长才有 龙之都。
  → 05:00 go_cave 报「调用计数异常」：04:43 起的 fight_helper 还在后台，同窗口并发调用。fight_helper 已经因此崩掉；以后跑寻路脚本前先确认没有 fight_helper。
- 05:01:24 百万1 带队进洞（徒弟已 31 级），05:01:56 第一朵花到手。
- 05:01:39–05:08:02 百万1 采 9 花 + 3 石（6.5 分）。
- **05:09 打蛇被拒 #1**：「队伍中有人刚刚战胜过地头蛇，赶紧让他回大个王处领赏吧！」——伏地魔1/2 的 224 停在 (2,1) 会挡住整队。
  → 05:10 全员回城卷 + PP鸡 龙之都，伏地魔1 在大个王：「遗忘洞穴的恐慌［进行中］」→「领取奖励」（+3290 经验 +687 潜能，无金币，224 变 (2,2) 再消失）→ 马上又给「为了经验值…我义不容辞 / 对不起，没兴趣」。**任务 224 可以反复做**：交完重接 =「☆遗忘洞穴的恐慌(28）［未接受］→ 我愿意接受 → 包在我身上」，又是 (1,)。伏地魔2 同样交 + 重接。
- 05:12–05:17 百万1 带队回洞、走二层到卧室。**05:17:12 打蛇被拦 #2**：点「开打」后 百万1 收到 **0x46f5 弹窗答题**「太阳系中距离太阳最近的行星是什么？」（选项文字是 关汉卿/王实甫…）。答题器（pid 8392，quizbot_39560.log）**只处理 0x46f4（战斗中答题），这个 0x46f5 它没看到**；按规矩我没回答。之后服务器对 百万1 带的队伍里任何人点任何 NPC 都不回（地头蛇、出口 10215）。
  → 05:24 用登录工具重登 百万1（这时选角列表顺序变了：槽1 百万1、槽2 十万1，按名字/ID 进成功），还是锁着。
  → 诊断：百万3 单独点蛇有对话；**百万2 当队长、百万1 当队员**的队伍点蛇也有对话 → 锁的是「百万1 当队长」。
  → 05:26 改 百万2 当队长重采：它身上已有 3 颗石头（伏击战掉落队员也拿），只需 9 花。卧室是封闭的，要先点出口 10215。
- 05:39:43 百万2 采齐 9 花（3 石早就有）。05:39:52–05:42:46 百万2 带队走到卧室。
- **05:42:46 百万2 点「开打」也弹 0x46f5**「月亮会自己发光吗？」。之后 百万1、百万2 单独点蛇都没回应（百万1 被锁 26 分钟以上，重登也没解开）。**停在这里**（见 REPORT）。

## 09:42 resume after user answered the 05:17/05:42 quizzes by hand
- All 5 roles: verification False, no dialog, no battle; 224 at (1,) for all.
- Team 百万1 + 伏地魔1/2 formed, dts.py (SHITU_LEADER=百万1) -> 「开打」 at 09:42:33.448, server sent a NEW 0x46f5 141 ms later
  (「分数中，分子在上还是分母在上？」), no battle; NPC clicks ignored again. log: research/shitu/logs/r2_dts5.log
- So 3 out of 3 「开打」 on 地头蛇 brought a 0x46f5 quiz to the leader. Each snake fight seems to need one quiz answered.
- 09:43:51 after the user answered 百万1's 2nd quiz: dts.py retry -> 开打 at once, no new 0x46f5, fight 19 s. log r2_dts6.log
  百万1 + 伏地魔1/2 -> 224 (2,1); 百万1 flowers/stones 9/3 -> 0/0. 百万2/3 still (1,) because they were NOT in the team.
  MISTAKE: round 1 had all 5 in the team and one kill gave everyone (2,1). Should have invited 百万2/3 too.
  Now masters at (2,1) block 百万2's fight (「队伍中有人刚刚战胜过地头蛇」).
- 09:57 user: test 百万2 + 百万3 + 欧皇 (lv70, char 166759, not a master, 224 at (1,)). lunhui15 CASTERS now from SHITU_CASTERS.
  Team 百万2 (leader, 9/3) + 欧皇 + 百万3. 开打 09:57:24.65 -> 0x46f5 at .724 (「什么工具能测量时间？」) -> no fight. log r2_dts7.log
  Pattern so far: the first 开打 by a leader brings a quiz; after the user answers it, the retry fights (百万1 09:43).
- 09:59:05 after the user answered 百万2's quiz: retry -> 开打 at once, no new quiz, 37 s. log r2_dts8.log
  百万2, 欧皇, 百万3 -> 224 (2,1); 百万2 flowers/stones 9/3 -> 0/0.
  TESTED: the master is NOT needed for the snake. Any team member whose 224 is at step 1 gets (2,1) from one kill;
  only the leader's flowers are used. 百万3 got credit without gathering anything.
  All 3 apprentices now 224 (2,1). Next: dagewang handin is part of trial3? -> trial3_run.
- 10:01 scroll home (百万1-3 + 伏地魔1 -> map 1). sell --junk 9/10/10 slots (+~3k each).
- 10:01:33-39 trial3_run --master 伏地魔1: all 3 got 强劲之棍 + 100k gold. 百万2/3 killed the snake WITHOUT the master
  (with 欧皇) and the NPC still accepted 「我已经完成考验了」 -> the 224 step (2,1) is all trial 3 checks. log r2_trial3.log
- 10:01:47 sell_tradable (weapon off): 3/3 slots each. 10:02 解除师徒 -30000 each (confirm text checked: 伏地魔1).
- 10:02:37-48 gold -> 伏地魔1: 151733 + 155068 + 155483 = +462284 exact; 伏地魔1 2107637 -> 2569921. apprentices 0.
- 10:03 delete_apprentices mvp01:222155:百万1 mvp02:222156:百万2 mvp03:222157:百万3 -> all accepted (72 h release).
## ROUND 2 DONE. 伏地魔1 start 2,257,437 -> 2,569,921 = net +312,484 (~104k / apprentice). 伏地魔2 2,221,365 -> 2,221,665.
