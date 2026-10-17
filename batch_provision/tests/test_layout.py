"""Unit tests for laying the station windows out (no game or window needed)."""
import unittest

from provisioner.layout import grid, order

AREA_2K = (0, 0, 2560, 1392)        # 2560x1440 without a 48 px taskbar


class Grid(unittest.TestCase):
    def test_five_1024x768_on_2k_three_by_two(self):
        self.assertEqual(grid(5, (1024, 768), AREA_2K),
                         [(0, 0), (768, 0), (1536, 0), (0, 624), (768, 624)])

    def test_eleven_800x600_on_2k_four_by_three_centre_shows(self):
        # 1 dispatcher + 3 well + 6 coast + 1 receiver; 816x639 = 800x600 with the window frame
        g = grid(11, (816, 639), AREA_2K)
        self.assertEqual(g[:5], [(0, 0), (581, 0), (1162, 0), (1743, 0), (0, 376)])
        self.assertEqual(g[-1], (1162, 752))

    def test_windows_that_fit_do_not_overlap(self):
        self.assertEqual(grid(4, (800, 600), AREA_2K), [(0, 0), (800, 0), (0, 600), (800, 600)])

    def test_every_window_stays_on_the_screen(self):
        for n in range(1, 9):
            for x, y in grid(n, (1024, 768), AREA_2K):
                self.assertTrue(0 <= x <= 2560 - 1024 and 0 <= y <= 1392 - 768, (n, x, y))

    def test_offset_work_area_and_empty(self):
        self.assertEqual(grid(1, (1024, 768), (100, 40, 2560, 1440)), [(100, 40)])
        self.assertEqual(grid(0, (1024, 768), AREA_2K), [])


class Order(unittest.TestCase):
    def test_by_role_then_id(self):
        rows = [{'station_id': s, 'role': r} for s, r in
                (('receiver1', 'receiver'), ('coast2', 'coast'), ('well1', 'well'), ('coast1', 'coast'),
                 ('dispatcher1', 'dispatcher'))]
        self.assertEqual([r['station_id'] for r in order(rows)],
                         ['dispatcher1', 'well1', 'coast1', 'coast2', 'receiver1'])


if __name__ == '__main__':
    unittest.main()
