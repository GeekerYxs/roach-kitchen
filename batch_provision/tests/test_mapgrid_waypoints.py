"""mapgrid.Grid.waypoints (2026-11-06 金刚猴 line: short walking legs instead of one 6650 px path-finder walk)."""
import math
import struct
import unittest

from provisioner.mapgrid import Grid


def grid(rows):
    """Synthetic grid: '.' walkable, '#' wall; cells 10 x 10 px."""
    cols = len(rows[0])
    head = struct.pack('<11I', 0, 0, 0, 0, 0, 10, 10, cols, len(rows), 0, 0)
    body = bytes(0 if ch == '.' else 1 for row in rows for ch in row)
    return Grid(head + body)


class Waypoints(unittest.TestCase):
    def test_legs_follow_the_path_and_end_at_goal(self):
        g = grid(['..........',
                  '########..',
                  '..........'])
        legs = g.waypoints((0, 0), (0, 20), step=40)
        self.assertEqual(legs[-1], (0, 20))
        self.assertGreater(len(legs), 2)
        # every leg is walkable and no leg is far longer than the step
        prev = (0, 0)
        for p in legs:
            self.assertTrue(g.walkable(*g.cell(*p)))
            self.assertLessEqual(math.dist(prev, p), 40 * 1.5 + 1)
            prev = p
        # the path goes round the wall's open end (x >= 80)
        self.assertTrue(any(p[0] >= 80 for p in legs))

    def test_other_part_has_no_path(self):
        g = grid(['....#....',
                  '....#....'])
        self.assertIsNone(g.waypoints((0, 0), (80, 0)))

    def test_near_goal_is_one_leg(self):
        g = grid(['.....'])
        self.assertEqual(g.waypoints((0, 0), (30, 0), step=600), [(30, 0)])


class Doors(unittest.TestCase):
    """2026-11-06 电锯杀人王 line: the PP鸡 path in 龙之都外城 walked into the 连锁商店 door (map 31)."""

    def test_block_walls_off_a_door_and_the_path_goes_round(self):
        g = grid(['..........'] * 7)
        door = (50, 30)
        straight = g.waypoints((0, 30), (90, 30), step=10)
        self.assertTrue(any(math.dist(p, door) < 20 for p in straight))
        g.block(door, 20)
        self.assertFalse(g.walkable(*g.cell(*door)))
        legs = g.waypoints((0, 30), (90, 30), step=10)
        self.assertEqual(legs[-1], (90, 30))
        self.assertTrue(all(math.dist(p, door) > 20 for p in legs))

    def test_outer_city_doors_are_listed(self):
        from provisioner import mapgrid
        self.assertIn((1928, 572), mapgrid.DOORS[20])      # 连锁商店 10420


if __name__ == '__main__':
    unittest.main()
