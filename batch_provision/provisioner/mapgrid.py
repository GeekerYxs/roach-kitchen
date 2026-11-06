"""Walkable grid of a map from the game's own data, path lengths on it, and the nearest spot from which the server
still answers a click on an NPC (user 2026-11-06: stand as close as needed, not on the NPC, to walk and fight less).

Format (facts from Gemini_Prj core/map_parser.py, checked 2026-11-06 on map 1150): the archives Patch1 / Patch /
Update / Game.Data (in that order, a patch wins) hold `map\\mapNNNNN.bar`: 44-byte header, u32[5] = cell height (8 px),
u32[6] = cell width (16 px), u32[7] = columns, u32[8] = rows, then one byte per cell: 0 = walkable, 0x80 = wall.
Check: the gate, the 琉璃瓶 and all ten bottles of 陷阱囚牢 stand on 0 cells while 77% of the map is wall.

Server reach (2026-11-06 live, raw 0x50 to 琉璃瓶 4077 in map 1150): answered from 100..500 px, also through walls
(300 / 440 px with a wall in between); no answer from 520 / 540 / 560 / 600 / 800 px -> straight-line distance about
500..520, walls do not matter. Bottles: 4069 answered from 427 px, but 4067 gave NO answer from 450 px (no chat line)
and the crystal from 199 px -> the reach differs per NPC (or the ResLib spot is off); REACH = 300 keeps a margin.
"""
import heapq
import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'runtime' / 'maps'
ARCHIVES = ('Patch1.Data', 'Patch.Data', 'Update.Data', 'Game.Data')
REACH = 300


def _crypt_table():
    t, seed = [0] * 0x500, 0x00100001
    for i1 in range(0x100):
        i2 = i1
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            hi = (seed & 0xFFFF) << 16
            seed = (seed * 125 + 3) % 0x2AAAAB
            t[i2] = hi | (seed & 0xFFFF)
            i2 += 0x100
    return t


_CT = _crypt_table()


def _hash(name, kind):
    s1, s2 = 0x7FED7FED, 0xEEEEEEEE
    for b in name.encode('gbk'):
        if 97 <= b <= 122:
            b -= 32
        s1 = (_CT[(kind << 8) + b] ^ (s1 + s2)) & 0xFFFFFFFF
        s2 = (b + s1 + s2 + (s2 << 5) + 3) & 0xFFFFFFFF
    return s1


def extract(game_dir, name):
    """One file from the game archives (MPQ-style hash table, zlib blocks); None when no archive has it."""
    h1, h2 = _hash(name, 1), _hash(name, 2)
    for arc in ARCHIVES:
        p = Path(game_dir) / arc
        if not p.is_file():
            continue
        with open(p, 'rb') as f:
            head = struct.unpack('<10I', f.read(40))
            f.seek(head[5])
            table = f.read(16 * head[7])
            for i in range(head[7]):
                a, b, _, rec = struct.unpack_from('<4I', table, i * 16)
                if a == h1 and b == h2:
                    f.seek(rec)
                    _, _, blocks, cur = struct.unpack('<4I', f.read(16))
                    out = bytearray()
                    for _ in range(blocks):
                        f.seek(cur)
                        _, _, comp, nxt = struct.unpack('<4I', f.read(16))
                        out += zlib.decompress(f.read(comp))
                        cur = nxt
                    return bytes(out)
    return None


def game_dir():
    from provisioner.addrscan import default_exe
    return Path(default_exe()).parents[2]          # <game>\v2.1\Win32\WAATClient.exe -> <game> holds Game.Data


class Grid:
    def __init__(self, data):
        h = struct.unpack('<11I', data[:44])
        self.sy, self.sx, self.cols, self.rows = h[5], h[6], h[7], h[8]
        self.g = data[44:44 + self.cols * self.rows]

    def cell(self, x, y):
        return round(x / self.sx), round(y / self.sy)

    def xy(self, c, r):
        return c * self.sx, r * self.sy

    def walkable(self, c, r):
        return 0 <= c < self.cols and 0 <= r < self.rows and self.g[r * self.cols + c] == 0

    def nearest_walkable(self, c, r, limit=20):
        for d in range(limit + 1):
            for dc in range(-d, d + 1):
                for dr in range(-d, d + 1):
                    if max(abs(dc), abs(dr)) == d and self.walkable(c + dc, r + dr):
                        return c + dc, r + dr
        return None

    def distances(self, start_xy):
        """Path length in px from start_xy to every reachable cell (8 neighbours, no corner cutting)."""
        s = self.nearest_walkable(*self.cell(*start_xy))
        dist = {s: 0.0}
        heap = [(0.0, s)]
        steps = [(dc, dr, math.hypot(dc * self.sx, dr * self.sy)) for dc in (-1, 0, 1) for dr in (-1, 0, 1)
                 if dc or dr]
        while heap:
            d, (c, r) = heapq.heappop(heap)
            if d > dist.get((c, r), math.inf):
                continue
            for dc, dr, w in steps:
                n = (c + dc, r + dr)
                if not self.walkable(*n) or (dc and dr and not (self.walkable(c + dc, r) and self.walkable(c, r + dr))):
                    continue
                nd = d + w
                if nd < dist.get(n, math.inf):
                    dist[n] = nd
                    heapq.heappush(heap, (nd, n))
        return dist

    def roomy(self, c, r):
        """Not hugging a wall: the client walks there without stalling against the edge."""
        return all(self.walkable(c + a, r + b) for a in (-1, 0, 1) for b in (-2, 0, 2))

    def touch_spot(self, dist, npc_xy, reach=REACH):
        """(path px, spot xy) of the reachable roomy cell within `reach` of npc_xy that is closest by path."""
        best = None
        c0, r0 = self.cell(*npc_xy)
        rc, rr = int(reach / self.sx) + 1, int(reach / self.sy) + 1
        for c in range(c0 - rc, c0 + rc + 1):
            for r in range(r0 - rr, r0 + rr + 1):
                d = dist.get((c, r))
                if d is None or math.dist(self.xy(c, r), npc_xy) > reach or not self.roomy(c, r):
                    continue
                if best is None or d < best[0]:
                    best = (d, self.xy(c, r))
        return best


def load(map_id, gdir=None):
    """Grid of map_id; cached under runtime/maps (the archives are ~2 GB, one read per map and PC)."""
    path = CACHE / f'map{map_id:05d}.bar'
    if not path.is_file():
        data = extract(gdir or game_dir(), f'map\\map{map_id:05d}.bar')
        if data is None:
            raise FileNotFoundError(f'游戏资源包里没有 map{map_id:05d}.bar')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return Grid(path.read_bytes())
