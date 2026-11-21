"""Unit test của khung PYTHON trong starter (ids, inputs, Session). Nếu nhóm thay bằng ngôn ngữ khác, XÓA file này
(và viết unit test tương đương bằng ngôn ngữ của nhóm); test hộp đen test_smoke_p1.py vẫn dùng nguyên."""

import unittest

from chonoi.errors import BadInput
from chonoi.ids import IdAllocator, id_key, sort_by_id
from chonoi.contract import load_contract
from chonoi.inputs import InputPlayer, LiveInputs, load_frames
from chonoi.runner import Session

from helpers import Workdir, frames, write_json


class Units(unittest.TestCase):
    def test_id_sorting(self):
        self.assertEqual([e["id"] for e in sort_by_id([{"id": "F10"}, {"id": "F2"}, {"id": "B1"}])], ["B1", "F2", "F10"])
        self.assertLess(id_key("F2"), id_key("F10"))

    def test_id_allocator_continues_after_max(self):
        a = IdAllocator()
        a.reserve("F3")
        a.reserve("F10")
        self.assertEqual(a.new("F"), "F11")
        self.assertEqual(a.new("F"), "F12")
        self.assertEqual(a.new("S"), "S1")

    def test_input_edges_and_inherit(self):
        with Workdir() as w:
            p = write_json(w.path("i.json"), frames({"tick": 1, "interact": True}, {"tick": 2, "move": [1, 1]}, {"tick": 3, "interact": False}, {"tick": 4, "interact": True}))
            pl = InputPlayer(load_frames(p))
            self.assertFalse(pl.advance(0).pressed("interact"))
            self.assertTrue(pl.advance(1).pressed("interact"))
            s2 = pl.advance(2)
            self.assertFalse(s2.pressed("interact"), "giữ true không lặp lại")
            self.assertAlmostEqual(s2.move[0] ** 2 + s2.move[1] ** 2, 1.0)
            pl.advance(3)
            self.assertTrue(pl.advance(4).pressed("interact"))
            self.assertEqual(pl.advance(5).move, s2.move, "move giữ giá trị cũ khi vắng frame")

    def test_bad_frames_raise(self):
        with Workdir() as w:
            with self.assertRaises(BadInput):
                load_frames(write_json(w.path("i.json"), frames({"tick": 0, "move": [2, 0]})))

    def test_catch_is_a_v10_button_and_attack_is_not(self):
        with Workdir() as w:
            load_frames(write_json(w.path("i.json"), frames({"tick": 0, "catch": True})))
            with self.assertRaises(BadInput):
                load_frames(write_json(w.path("j.json"), frames({"tick": 0, "attack": True})))

    def test_live_inputs_keep_fast_tap_edge(self):
        li = LiveInputs()
        li.set(interact=True)
        li.set(interact=False)  # bấm và nhả giữa hai tick: vẫn phải thấy một cạnh lên
        self.assertTrue(li.advance().pressed("interact"))
        self.assertFalse(li.advance().pressed("interact"))
        li.set(move=[1, 1], catch=True)
        st = li.advance()
        self.assertTrue(st.pressed("catch"))
        self.assertAlmostEqual(st.move[0] ** 2 + st.move[1] ** 2, 1.0)

    def test_session_steps_gather_and_dock(self):
        tuning = load_contract()["tuning"]
        s = Session("gather", tuning, {"hold": ["ca_loc"]}, 1)
        self.assertEqual(s.snapshot()["tick"], 0)
        li = LiveInputs()
        self.assertEqual(s.step(li.advance()), [])
        li.set(interact=True)
        rows = s.step(li.advance())
        self.assertEqual([r["name"] for r in rows], ["gather_end"])
        self.assertTrue(s.done)
        self.assertEqual(s.snapshot()["tick"], 2)
        self.assertEqual(s.end_row()["reason"], "docked")

    def test_session_quan_uses_customer_reserved_ingredient(self):
        tuning = load_contract()["tuning"]
        scenario = {
            "random_customers": False,
            "stock": {"ca_loc": 1},
            "player": {"pos": [2, 8]},
            "customers": [{
                "id": "C1",
                "table_id": "T1",
                "dish": "ca_loc_nuong_trui",
                "state": "waiting",
                "reserved": {"ca_loc": 1},
            }],
        }
        s = Session("quan", tuning, scenario, 1)
        li = LiveInputs()
        li.set(interact=True)
        rows = s.step(li.advance())
        self.assertEqual([r["name"] for r in rows], ["cook_started"])
        snapshot = s.snapshot()
        self.assertEqual(snapshot["stock"], {})
        self.assertEqual(snapshot["stoves"][0]["state"], "cooking")
        self.assertEqual(snapshot["customers"][0]["reserved"], {})


if __name__ == "__main__":
    unittest.main()
