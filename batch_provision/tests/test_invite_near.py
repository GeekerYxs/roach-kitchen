"""well10.invite_near (user 2026-11-01: a leader can have 4 invites out at once) and teamwalk's lost-invite note."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'research' / 'shitu'))

import teamwalk  # noqa: E402
import well10  # noqa: E402


class Server:
    def __init__(self, accept_ok=True):
        self.team, self.invites, self.accept_ok, self.log = [], set(), accept_ok, []


class C:
    def __init__(self, srv, name, cid, xy, map_id=20, in_battle=False):
        self.srv, self.name, self.char_id, self.mem = srv, name, cid, self
        self.xy, self.map_id, self.in_battle, self.own_team = xy, map_id, in_battle, ()
        self.game = NS(team_invite=self.invite, team_accept=self.accept)

    def invite(self, cid, *a):
        self.srv.log.append(('invite', cid))
        self.srv.invites.add(cid)

    def accept(self):
        self.srv.log.append(('accept', self.name))
        if self.srv.accept_ok and self.char_id in self.srv.invites:
            if not self.srv.team:
                self.srv.team.append(1)
            self.srv.team.append(self.char_id)

    def team(self):
        return tuple(self.srv.team) if self.char_id == 1 else self.own_team

    def world(self):
        return NS(map_id=self.map_id, x=self.xy[0], y=self.xy[1], in_battle=self.in_battle)


def run(lead, others):
    srv = lead.srv
    with mock.patch.object(well10.w, 'read_team', lambda mem: NS(inviter=1 if mem.char_id in srv.invites else 0)), \
            mock.patch.object(well10.w, 'read_level', lambda mem: 70), \
            mock.patch.object(well10.w, 'read_invite_byte', lambda mem: 0), \
            mock.patch.object(well10.t, 'say', lambda s: None), \
            mock.patch.object(well10.time, 'sleep', lambda s: None), \
            mock.patch.object(well10.t, 'wait', lambda cond, timeout, what: cond() or
                              (_ for _ in ()).throw(well10.t.Stop(what))):
        well10.invite_near(lead, others)
    return srv


class InviteNear(unittest.TestCase):
    def test_all_invites_before_any_accept(self):
        srv = Server()
        lead = C(srv, 'M', 1, (100, 100))
        apps = [C(srv, f'a{i}', 10 + i, (100 + 20 * i, 100)) for i in range(4)]
        run(lead, apps)
        kinds = [k for k, _ in srv.log]
        self.assertEqual(kinds, ['invite'] * 4 + ['accept'] * 4)
        self.assertEqual(srv.team, [1, 10, 11, 12, 13])

    def test_far_other_map_battle_or_teamed_are_left_to_form_team(self):
        srv = Server()
        lead = C(srv, 'M', 1, (100, 100))
        near = [C(srv, 'a', 10, (120, 100)), C(srv, 'b', 11, (140, 100))]
        far = C(srv, 'f', 12, (900, 100))
        other = C(srv, 'o', 13, (100, 100), map_id=1)
        fight = C(srv, 'x', 14, (100, 110), in_battle=True)
        teamed = C(srv, 't', 15, (100, 120))
        teamed.own_team = (99, 15)
        run(lead, near + [far, other, fight, teamed])
        self.assertEqual([x for k, x in srv.log if k == 'invite'], [10, 11])

    def test_one_near_member_uses_the_old_path(self):
        srv = Server()
        lead = C(srv, 'M', 1, (100, 100))
        run(lead, [C(srv, 'a', 10, (120, 100)), C(srv, 'f', 12, (900, 100))])
        self.assertEqual(srv.log, [])

    def test_lost_accepts_do_not_raise(self):
        srv = Server(accept_ok=False)
        lead = C(srv, 'M', 1, (100, 100))
        run(lead, [C(srv, 'a', 10, (120, 100)), C(srv, 'b', 11, (140, 100))])
        self.assertEqual(srv.team, [])


class OfflineNote(unittest.TestCase):
    def test_note(self):
        import r4_util
        cs = [NS(name='M'), NS(name='a')]
        with mock.patch.object(r4_util, 'offline', lambda n: n == 'a'):
            self.assertIn('a 掉线了', teamwalk._offline_note(*cs))
        with mock.patch.object(r4_util, 'offline', lambda n: False):
            self.assertEqual(teamwalk._offline_note(*cs), '（两边都在线）')
        with mock.patch.object(r4_util, 'offline', mock.Mock(side_effect=OSError('x'))):
            self.assertIn('掉线检查失败', teamwalk._offline_note(*cs))


if __name__ == '__main__':
    unittest.main()
