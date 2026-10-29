# battlelog — technical notes (for agents and code changes)

User-facing guide (Chinese): [docs/BATTLELOG.md](../../docs/BATTLELOG.md). This file is the reference for changing
the code: data flow, every packet layout with the evidence behind it, the database schema, invariants, how to add a
field, and what is still unknown. Keep it current when you change a layout or a column.

Built 2026-10-29 on client 2.101 (layouts read from 2.100/2.101 tap files of 2026-10-26..29).

---

## 1. Data flow

```
 game client (WAATClient.exe)
   ├─ provision_native.dll tap (MinHook on recv / client send fn) ──► runtime/tap_<pid>.jsonl + tap_<pid>_codec.json
   │                                                                  research/shitu/runtime/… (attach_tap.py copy)
   └─ memory (ReadProcessMemory only)
         │
 decode.tap_packets(lines, tables) ─► [Packet(tick, dir, opcode, body)]      (pure)
 decode.assemble(packets)          ─► [Battle] incl. statuses, raw bodies, in-battle packets   (pure)
 store.to_row(battle, src, pid, anchor) ─► row dict ─► store.save()  ─► logs/battlelog/battles.sqlite : battles
 store.fill_from_teammates(db)     ─► role / level from other files' lineups
 live.MemTracker.feed(MemSample)   ─► [MemBattle] ─► live.save() ─► mem_battles        (stage 2, pure core)
 live.merge(db)                    ─► battles.{mem_level, mem_exp_gain, gold_delta, bag_delta, quiz_count, quiz_s}
 report.build(db, items.csv, maps) ─► markdown (stage 4)
```

Everything that decides something is a pure function over bytes / rows and is unit-tested
(`tests/test_battlelog.py`, `tests/test_battlelog_live.py`). Game access lives only in `live.read_sample` /
`live.run` (read-only) and nothing in this package ever writes to the game or calls game functions.

## 2. Modules

| File | Role |
|---|---|
| `decode.py` | Tap framing + codec, packet layouts (0x4100 / 0x4101 / 0x472A / 0x4210 / 0x4112 / 0x42CF / client 0x1003-0x1005), `assemble`, `events`, `pack_packets` / `unpack_packets` |
| `store.py` | SQLite schema + migration (`connect` adds missing columns, loads `npcs`), `to_row`, `event_columns`, `status_columns`, `rebuild_events`, `fill_from_teammates`, `DECODER` version |
| `live.py` | Stage 2: `MemSample` / `MemTracker` / `MemBattle` (pure), `mem_battles` table, `merge`, `read_sample` + `run` (the loop) |
| `report.py` | Stage 4: `build(db, items_csv, map_names)` -> markdown |
| `__main__.py` | CLI: `import [--force] [folders]`, `summary`, `rebuild`, `report`, `live <toml>`; `import_file` |
| `monsters.csv` | copy of client `ResLib/MonsterID.csv`: `npc_id,name,catchable,kind` (kind 5 稀有, 6 BOSS) |
| `maps.csv` | copy of client `ResLib/MapNameLib.csv`: `map_id,kind,name` |

Related outside the package: `provisioner/world.py` (`read_world`, `read_level`, `read_gold`, `read_bag`,
`read_fighter_levels`), `expwatch/` (exp table `explib.csv`, `SESSION_EXP`, `find_pids`, `module_base`),
`provisioner/addrscan.py` (signature `BATTLE_GRADES`).

## 3. Tap file format and framing

`tap_<pid>.jsonl`, one JSON object per line: `{"kind", "tick", "opcode", "caller_rva", "length", "hex"}`.

| kind | meaning | used |
|---|---|---|
| `wire_recv` | raw socket bytes from the server (one TCP stream, frames span records) | decoded |
| `request` | the client's own send function, **plain** opcode + body before encoding | kept as `SEND` packets |
| `wire_send` / `wire_WSASend` | encoded outgoing bytes | ignored (`request` has them plain) |

`tick` = GetTickCount ms of the record. Receive frames: `<u16 ~len><u16 opcode><body>`; body byte i is decoded with
`tables[(index + i) % 10]`, `index = ((opcode << 8) ^ ~len_field) % 10`, tables from `tap_<pid>_codec.json`
(`decode` = 10 hex strings of 256 bytes, dumped by the DLL). A frame gets the tick of the record holding its first byte.
`tap_packets` drops consumed bytes as it goes (memory flat on 50 MB files; the old `protocol.TapReader` is quadratic
on big files — do not use it for imports).

**Wall time**: `anchor = file mtime - last_record_tick / 1000` (the DLL writes each record at once, so mtime = last
record). `start_time = anchor + tick / 1000`. Checked: against the exp monitor's memory timestamps the offset is a
constant ~1.6 s (the monitor's "end" is when the battle flag drops), identical for three roles of one boot.
All tap files of one machine share the GetTickCount clock — that is what `fill_from_teammates` relies on.
32-bit tick wrap (49.7 days uptime) is not handled.

## 4. Packet layouts

Offsets are into the decoded body. "Evidence" says how it was established — keep that standard for new fields.

### 4.1 0x4100 battle map (S->C, 6 B)
`<u16 map_id><u16 x><u16 y>` — map and encounter position. First packet of a battle.

### 4.2 0x4101 battle lineup (S->C)
```
head 46 B : +0 u32 own char id, +40 u8 own client pos, +41 u8 own pet pos, +42 u8 n players, +43 u8 n units
players   : n x 91 B, the OTHER players (the own role is NOT listed)
            +0 i64 hp, +8 i64 hp max, +24 u32 char id, +28 u32 (3 seen; class?), +36 7 x i32 (equipment looks, -1 none),
            +64 u32 level, +72 u8 (1), +73 u8 client pos, +74 char[17] name (GBK, NUL-terminated)
units     : n x 56 B, monsters and the teammates' pets (own pet not listed)
            +0 i64 hp, +8 i64 hp max, +24 u32 npc id, +28 u32 level, +37 u8 client pos, +38 u8 kind (1 monster, 2 pet),
            +40.. leftovers / pet names (not reliable)
trailer   : 5 of 1171 files end every 0x4101 with 6 more bytes, always 30 58 0a 00 01 00 (meaning unknown)
```
`parse_lineup` raises when `len != 46 + 91 p + 56 u (+ 6)`; the battle is still stored with the error text.
Evidence: 8阵图 units 1197/1198/1203 at 21/22 = the memory fighter-level rows read live; names match the client
monster table and Codex's 2026-09-30 screen check (猛男鼹鼠 21, 黄花闺女 21, 回魂丧者 22); player names / levels
match the 师徒 roster; own pos = the one position missing from the players (15-19), own pet pos = the one missing
from the pets (10-14).

### 4.3 0x472A battle result (S->C, 393 / 403 / 404 / 414 / 415 / 425 B seen)
```
+0   u32 char id (own; teammates' results are not sent to you)
+4   i64 character exp (signed: a death can give a net loss)
+12  i64 0 so far
+20  i64 pet exp
+28  u32 pet training exp
+32  u32 potential
+40  u32, +48 u32 : constant per role (e.g. 4060 / 1230 on a 70 master; 1207 / 94 on an apprentice) — unknown
+56  u32 : 28601 on apprentices, 0 on masters — unknown
+140 10 x i32 monster npc ids (-1 = none)
+356 u8 monster count, +357 u8 (0/1/2), +358 u8 item count, +359 u8 (1)
+371 items, 11 B each: <u32 item id><u16 qty><u16 1><u8 bag slot><u16 1>
after the items: <i64 A><i64 B><u32 C> + 2 B (+5 B on some) — A/B vary per battle on apprentices (467..881 / 143..304),
     constant 1744 / 748 on a 70 master; C 840..990 or 0. NOT gold (battles give no gold, user 2026-10-29). Unknown.
```
Evidence: +4 equals the exp monitor's memory gain in 1697 / 1706 battles of 亿万1/17/25 after aligning by time
(misses = battles the monitor split differently). +20/+28/+32 are Codex's panel-checked offsets
(`D:\Codes\OpenAiCodex\game_smsm2\EXP_03B_GRASSLAND_TRIAL.md`, older 36+ B layout, same offsets); consistent with
the status analysis below (exp 1.99x with status 1001, pet 1.02x, potential 1.00x). Items: every id of 1600 drops of
three roles exists in `factory/data/items.csv`.
2.101 panel check (user screenshot 2026-10-29, 欧皇丨花花乀 lv70 + pet 魔力布老虎 lv44 in 通天塔二区, panel:
exp 1, potential 0, pet exp 3014, training 3, drop 叉子): that window had no tap, so not byte-aligned, but every
value has the shape the database gives these offsets — +4 at a +30 gap is 1~2 (12 k lv70 battles on 281), +32 is 0
whenever +4 <= 2 (12.8 k battles), +28 takes only the discrete values 0/3/7/10/14/20 (3 in 6117 battles,
independent of +20), and +20 follows the pet's own level, not the owner's (lv70 pets 1~2, the lv36 apprentices'
pets 2950~3090 in the same map). Byte-exact proof still needs one panel from a window with the DLL.

### 4.4 0x4210 level up (S->C, 12+ B)
`<u32 level (low u16 = level, high bits = flags)><u32><u32 char id>` — use the low u16 only (Codex saw 65545).

### 4.5 0x4112 fighter out (S->C, 2 B)
`<u8 client pos><u8 1>` — that position is dead / out. Evidence: in 20000 battles every monster position got one in
99.97 % of the battles. Own death = own pos in the set. (Catching a monster probably also removes it — not checked.)

### 4.6 0x42CF character status (S->C, 28 B)
`<u32 char id><u32 status id><i64 seconds left><u32 value><u32 0><u32 1>`
Sent at login, when a status is added or extended, and with 0 seconds when it ends. Status ids =
`ResLib/SpecialStatusLib.csv`: **1001 多倍角色经验, 1002 多倍角色潜能, 1003 多倍宠物经验, 1004 多倍宠物训练点**
(value = multiplier, 2), 1007 死亡不扣经验, 1019 +N % character exp (value = percent), 1026 多倍神识经验, 1022 月卡...
Timers run while online and freeze offline (status text). `assemble` keeps `{char: {status: (value, end tick)}}` over
the whole file and snapshots the own role's active statuses at each battle's lineup.
Evidence: 散福 claims show 3600 -> 7200 -> 10800 s; within the same (map, level) cell, battles with 1001 active give
1.99x character exp, 1.02x pet exp, 1.00x potential (14 cells).
Do not confuse with 0x40A0 (NPC / player list, contains those numbers by accident) or 0x42CE (`fc 03 00 00` once per
battle, = status 1020 世界BOSS?; unknown).

### 4.7 Client commands (C->S, `request` records)
Disassembled 2026-10-29 on 2.101:
- **0x1004** `SendFightCmdPacket` RVA 0x16F4B0, 12 B: `+5 u8 server target pos`, `+6 u8 (action << 1) | is_pet`,
  `+8 u32 param` (pet magic: `id << 16 | level`, e.g. 1504 烈焰爆发 lv13); +0..4 and +7 are uninitialised stack.
  Actions (`game.py`, `decode.ACTIONS`): 2 attack, 3 magic, 4 (11 times, pets only; defend?), 8 escape, 0xB catch.
  History counts: (3, pet) 38692, (2, player) 2605, (2, pet) 585, (8, player) 409, (4, pet) 11.
- **0x1005** `CastSkillToFighter` RVA 0x134E0, 16 B: player skill (`+6` = 8, or 6 for a player magic). Counted as `skill`.
- **0x1003** `UseItemToFighter` RVA 0x13310, 8 B: `+5 target`, bag slot assumed at `+7` (**not verified**: no 0x1003
  in the whole 2026-10 history). Counted as `item`, slot listed in `items_used`.
- 0x1001 (6 B, once per battle start), 0x1F51 (empty, heartbeat-ish) — not used.
Converting client <-> server positions: see `SendFightCmdPacket` (pos >= 15: -15; >= 10: -5; < 5: +15; else +5, when
the own real pos <= 10 and the side flag is set).

### 4.8 Other in-battle server packets (stored raw, not decoded)
`0x4104` (4/5 B, `<u16 a>[<u16 b>]<u8 0><u8 pos>`, animation per position), `0x4105` (`<u8 pos>`, actor turn),
`0x4106` (`<u8>`/`<u16 skill><u8 pos>`), `0x4108` (12 / 28 B per position, `<u32 own id><u32 0><u8 pos>…` + buff?),
`0x4109` (variable, one per action: actor, skill, then effects `<u32 code><i64 value><u32>`; code 405 looks like
damage, 403 / 407 / 409 / 411 seen), `0x4111` (`<u8 pos><u8 0..4>`), `0x4211` (after the battle, per team member),
`0x47C0`, `0x4F52`, `0xEFFE`.

## 5. Memory (stage 2, read-only)

`live.read_sample` = `world.read_world` (in battle, map, x/y, `verification` = quiz panel ui+0x12F4 or boss quiz
ui+0x12F8 active), `world.read_level` (session+0xF00), exp i64 at session+0xEF0 (`expwatch.SESSION_EXP`),
`world.read_gold` (session+0x16B0+0x8800), `world.read_bag` (summed per item id). Fighter levels:
`world.read_fighter_levels` = battle+0x867C, 20 rows x 0x2C, +0x10 client pos (-1 empty, rows NOT in pos order),
+0x28 level (from Lua `GetFighterLevel` RVA 0x132C0; signature `BATTLE_GRADES` in addrscan; 2.98/2.99 copy 0x8674).
**Fighter HP is not a plain field**: no u32 equal to the known monster HP max (767/652/825) in the 0x510-byte fighter
struct during 八阵图 battles; Lua `GetHp()` goes through a protected value wrapper (project notes, 2026-10-06).

`MemTracker` semantics: a battle opens on the in-battle flag rising, ends when it drops, and is closed at the next
rise (or `IDLE_CLOSE` = 60 s later). Exp gain via `expwatch.core.gained` (handles level-ups). Gold / bag "before" =
state at the previous close, "after" = state at this close, so a cycle = previous battle end -> this battle end
(drops, item use, shop sells, mail all land there). Quiz count = rising edges of `verification` in the cycle, quiz_s =
time it was up. `patrol_s` = this start - previous end. The first battle seen (already running at start) is skipped.

`merge(db, window_s=3)`: battles row <- mem_battles row with the same `pid` and |start_time diff| <= 3 s, only while
`battles.mem_level is null` (idempotent). Also fills `level` / `role` where the tap had none.

## 6. Database (`logs/battlelog/battles.sqlite`)

### battles (one row per battle and tap file; unique (source, start_tick); re-import replaces)
| Column | Meaning |
|---|---|
| source, pid | tap file path, process id |
| char_id, role | own char id (0x4101 +0); role = own name from a teammate's lineup or the live recorder |
| start_tick, end_tick | GetTickCount of 0x4100 (or 0x4101) and of the own 0x472A (null = no result) |
| start_time, end_time | wall time (§3) |
| fight_s, patrol_s | end - start; previous result -> this start (null for a file's first battle) |
| map_id, x, y | 0x4100 |
| level, level_after | own level (teammate lineup within 3 s, or memory); 0x4210 inside the battle |
| own_pos, own_pet_pos | 0x4101 +40 / +41 |
| exp, pet_exp, pet_training, potential | 0x472A |
| monster_count, monster_levels | monsters in the lineup; 'a b c' ascending |
| monsters, pets | json `[[npc_id, level, pos, hp_max], …]` (pets = teammates' pets) |
| players | json `[[char_id, name, level, pos, hp_max], …]` (other players) |
| items | json `[[item_id, qty, bag_slot], …]` (drops) |
| packet_count, opcodes | packets inside the battle; json `{"<dir>:0x<op>": count}` (dir 0 = recv, 1 = send) |
| raw_map, raw_lineup, raw_result | bodies as received |
| packets | zlib of `<i32 ms since start_tick><u8 dir><u32 opcode><u32 len><body>` per packet (`unpack_packets`) |
| errors, decoder | parse errors ('; '-joined); DECODER version that wrote the row |
| kills, own_dead, own_pet_dead, mates_dead | from 0x4112 vs lineup positions |
| escape_tries, escaped | own escape commands; escaped = tried and not every monster went out |
| player_cmds, pet_cmds, items_used | json counts per action name; json list of bag slots (0x1003) |
| statuses | json `{"<status id>": [value, seconds_left]}` active at the start |
| x_exp, x_potential, x_pet_exp, x_pet_training, exp_percent | multipliers (1 / 2) and the 1019 percent |
| mem_level, mem_exp_gain, gold_delta, bag_delta, quiz_count, quiz_s | merged from mem_battles (§5) |

### other tables
- `sources(path, pid, size, mtime, anchor, battles, imported_at)` — import bookkeeping (skip unchanged files).
- `npcs(npc_id, name, catchable, kind)` — loaded from `monsters.csv` on first connect.
- `mem_battles(role, pid, char_id, start_time, end_time, map_id, x, y, level, level_after, exp_before, exp_after,
  exp_gain, gold_before, gold_after, bag_delta, quiz_count, quiz_s, patrol_s)` — unique (pid, start_time).

### versions / migration
`store.DECODER`: 1 = first import, 2 = battle events, 3 = statuses. `store.connect` adds every `EVENT_COLUMNS`
column an older file lacks; `live.init` adds `MERGE_COLUMNS` and `mem_battles`. Event columns can be recomputed from
the stored packets (`rebuild`); **status columns cannot** (0x42CF packets arrive outside battles and are not stored),
so a status change needs `import --force`.

Useful queries:
```sql
-- single exp per hour by map and level (what report §1 does)
select map_id, level, count(*), sum(exp / x_exp) * 3600.0 / sum(fight_s + min(coalesce(patrol_s, 0), 120))
from battles where end_tick is not null and level is not null group by 1, 2 having count(*) >= 30;
-- monsters of a map with names
select n.name, json_extract(m.value, '$[1]') lv, count(*) from battles b, json_each(b.monsters) m
join npcs n on n.npc_id = json_extract(m.value, '$[0]') where b.map_id = 281 group by 1, 2 order by 3 desc;
```

## 7. How to add a field

1. Find it in the raw data first: `decode.unpack_packets(row['packets'], row['start_tick'])` or `raw_result` etc.
   over many rows; write the hypothesis down with its evidence (a count over the history, a match against memory or
   a screenshot, a disassembly). No guessed fields — unknown bytes stay raw.
2. Parse it in `decode.py` (pure, raise `ValueError` on a length mismatch rather than reading garbage).
3. Add the column: if it is computable from one battle's stored bodies/packets, add it to `store.EVENT_COLUMNS` and
   `event_columns` (then `python -m battlelog rebuild` fills history in ~12 s). If it needs packets outside the
   battle (like 0x42CF), carry it on `decode.Battle` from `assemble`, add a `*_columns` helper, and run
   `import --force` (~1.5 min for 1.3 GB).
4. Bump `store.DECODER`, add a test with real bytes (put samples in `tests/battlelog_sample.py`; one real 八阵图
   battle is there already), document the layout + evidence in §4 here and the meaning in docs/BATTLELOG.md §1.

## 8. Testing

```bash
python -X utf8 -m unittest discover -s tests -p "test_battlelog*.py"      # 24 tests, no game needed
python -X utf8 -m unittest discover -s tests                              # whole repo (864 on 2026-10-29)
```
Samples: `tests/battlelog_sample.py` (real 0x4100 / 0x4101 / 0x472A of 亿万20 in 八阵图). Synthetic packets are
built in the tests with a known codec (table k maps v -> v + k + 1) so framing / index math is exercised.

## 9. Pitfalls met while building it

- **Writing test files from a shell heredoc**: `b'\x00\x01'` in a Python generator string became real NUL bytes
  in the file ("source code string cannot contain null bytes"). Use the Write/Edit tools for code with escapes.
- `Path.write_text` on Windows writes CRLF; git autocrlf normalises, harmless.
- `protocol.TapReader` re-slices its buffer per frame (quadratic) — a 26 MB file never finished. Use `tap_packets`.
- SQLite does not allow an outer column in a correlated subquery's ORDER BY inside UPDATE — `fill_from_teammates`
  does the nearest-time match in Python (bisect) instead.
- The 0x4101 player list excludes the own role: do not look for the own level there.
- Medians of mixed populations mislead (70 masters get ~2 exp per battle on low maps): report compares within the
  same (map, level) cell and takes medians over maps.

## 10. Open questions

- Per-round lowest HP: decode `0x4109` effects (needs a solo battle where the start HP is known) or reproduce the
  `GetHp()` decode read-only (disassemble the protected-value wrapper).
- 0x472A +12, +40, +48, +56 and the tail after the items (A / B / C); 0x4101 player +28 and the 6-byte trailer.
- 0x4111, 0x42CE, 0x4108 28-byte variant (buff id + value?).
- 0x1003 bag-slot offset (no item use in the history yet: use a potion in battle with the tap on and check).
- Whether catching a monster also sends 0x4112.
