"""Buổi tối — Mở Quán. KHUNG: đi lại, chặn biên, đồng hồ, kho nạp từ file/scenario.

Nhóm viết tiếp (PRD-0 mục F, Quán):
  TODO(nhóm, lát 3): khách đến theo lịch, chọn món nấu được, giữ chỗ nguyên liệu, kiên nhẫn,
                     bỏ đi (customer_left), no_dish, vòng đời khách.
  TODO(nhóm, lát 4): interact tại bếp/bàn (cook_started, dish_ready, dish_picked, served),
                     ăn xong trả tiền (paid), boa, uy tín, hết ca (quan_end).
"""

import math

from ..ids import sort_by_id
from .ramp import ramp_velocity

TICK = 60.0


class QuanSim:
    mode = "quan"
    phase = "quan"

    def __init__(self, tuning, scenario, streams, ids, inventory=None):
        t = tuning["quan"]
        self.t = t
        self.menu = tuning["menu"]
        self.rng = streams
        self.ids = ids
        p = scenario.get("player", {})
        self.pos = list(p.get("pos", t["start_pos"]))
        self.vel = [float(c) for c in p.get("vel", [0.0, 0.0])]
        self._tgt = None
        self._ramp_left = 0
        # kho: --inventory HOẶC scenario.stock (cả hai -> cli đã báo mã 2)
        self.stock = dict(inventory if inventory is not None else scenario.get("stock", {}))
        self.hand = scenario.get("hand")
        self.time_left_ticks = scenario.get("time_left_ticks", int(round(t["duration_s"] * 60)))
        self.reputation = scenario.get("reputation", t["reputation_initial"])
        self.stoves = [dict(s, state=s.get("state", "idle"), dish=s.get("dish"),
                            cook_ticks_left=s.get("cook_ticks_left", 0), ready_ticks=s.get("ready_ticks", 0))
                       for s in self._merge(t["stoves"], scenario.get("stoves", []))]
        self.tables = self._merge(t["tables"], scenario.get("tables", []))
        self.customers = []
        for c in scenario.get("customers", []):
            customer = dict(c)
            customer.setdefault("state", "waiting")
            customer.setdefault("dish", self._choose_any_dish())
            customer.setdefault("patience_ticks_left",
                                 int(round(t["patience_s"] * TICK)))
            customer.setdefault("eat_ticks_left",
                                 int(round(t["eat_s"] * TICK)))
            customer.setdefault("reserved", {})
            self.customers.append(customer)
        for e in self.customers:
            ids.reserve(e["id"])
        self.money = 0
        self.earned = 0
        self.shift_earned = 0
        self.done = False
        self.reason = None
        self._next_customer_tick = int(t["first_customer_tick"])
        self._customer_seq = 0
        self._tick_count = 0
        self.random_customers = scenario.get("random_customers", True)

    @staticmethod
    def _merge(defaults, updates):
        by_id = {d["id"]: dict(d) for d in defaults}
        for u in updates:
            if u["id"] not in by_id:
                from ..errors import BadInput
                raise BadInput(f"id bếp/bàn không tồn tại: {u['id']}")
            by_id[u["id"]].update(u)
        return sort_by_id(list(by_id.values()))

    def snapshot(self) -> dict:
        occupied = {c["table_id"]: c["id"] for c in self.customers}
        return {
            "player": {"pos": self.pos},
            "stock": {k: self.stock[k] for k in sorted(self.stock) if self.stock[k] > 0},
            "hand": self.hand,
            "stoves": [{k: s.get(k) for k in ("id", "pos", "state", "dish", "cook_ticks_left", "ready_ticks", "customer_id")}
                       for s in self.stoves],
            "tables": [{"id": tb["id"], "pos": tb["pos"], "customer_id": occupied.get(tb["id"])} for tb in self.tables],
            "customers": sort_by_id(self.customers),
        }

    def step(self, inp):
        events = []
        self.time_left_ticks = max(0, self.time_left_ticks - 1)
        self._tick_count += 1
        # cooking and eating are state machines
        for stove in sort_by_id(self.stoves):
            if stove["state"] == "cooking":
                stove["cook_ticks_left"] = max(0, int(stove["cook_ticks_left"]) - 1)
                if stove["cook_ticks_left"] == 0:
                    stove["state"] = "ready"
                    stove["ready_ticks"] = 0
                    events.append(("dish_ready", {"stove_id": stove["id"], "dish": stove["dish"]}))

        left = []
        for customer in sort_by_id(self.customers):
            state = customer.get("state", "waiting")
            if state == "waiting":
                customer["patience_ticks_left"] = max(0,
                    int(customer.get("patience_ticks_left",
                                    round(self.t["patience_s"] * TICK))) - 1)
                if customer["patience_ticks_left"] == 0:
                    for k, v in customer.get("reserved", {}).items():
                        # reservations are separate from stock, so they simply disappear
                        pass
                    customer_id = customer["id"]
                    self.reputation = max(self.t["reputation_min"],
                                          self.reputation + self.t["left_reputation_delta"])
                    events.append(("customer_left", {"customer_id": customer_id,
                                                     "table_id": customer["table_id"],
                                                     "dish": customer.get("dish")}))
                    continue
            elif state == "eating":
                customer["eat_ticks_left"] = max(0,
                    int(customer.get("eat_ticks_left",
                                    round(self.t["eat_s"] * TICK))) - 1)
                if customer["eat_ticks_left"] == 0:
                    dish = customer["dish"]
                    price = int(self.menu[dish]["price"])
                    patience_max = int(round(self.t["patience_s"] * TICK))
                    patience_left = int(customer.get("patience_ticks_left", patience_max))
                    ratio = patience_left / patience_max
                    tip = 0
                    if ratio >= self.t["tip_min_patience_ratio"]:
                        tip = round(price * self.t["tip_rate"])
                        self.reputation = min(self.t["reputation_max"],
                                              self.reputation + self.t["tip_reputation"])
                    self.money += price + tip
                    self.earned += price + tip
                    self.shift_earned += price + tip
                    events.append(("paid", {"customer_id": customer["id"], "table_id": customer["table_id"],
                                            "dish": dish, "price": price, "tip": tip}))
                    if tip > 0:
                        events.append(("tip", {"customer_id": customer["id"], "amount": tip}))
                    continue
            left.append(customer)
        self.customers = left
        self._move(inp)
        if inp.pressed("interact"):
            stove_candidates = [(math.dist(self.pos, s["pos"]), s["id"], s) for s in self.stoves
                                if math.dist(self.pos, s["pos"]) <= self.t["interact_radius"]]
            table_candidates = [(math.dist(self.pos, tb["pos"]), tb["id"], tb) for tb in self.tables
                                if math.dist(self.pos, tb["pos"]) <= self.t["interact_radius"]]
            candidates = [(d, 0, oid, obj) for d, oid, obj in stove_candidates]
            candidates += [(d, 1, oid, obj) for d, oid, obj in table_candidates]
            if candidates:
                _, kind, _, obj = min(candidates, key=lambda c: (c[0], c[1], c[2]))
                if kind == 0:
                    events.extend(self._interact_stove(obj))
                else:
                    events.extend(self._interact_table(obj))

        if self.random_customers and self._tick_count >= self._next_customer_tick:
            events.extend(self._spawn_customer())
            self._next_customer_tick += int(round(self.t["customer_interval_s"] * TICK))
        if self.time_left_ticks <= 0:
            self.done = True
            self.reason = "time"
            events.append(("quan_end", {"reason": "time", "money": self.money, "earned": self.earned,
                                        "shift_earned": self.shift_earned, "reputation": self.reputation}))
        return events

    def _choose_any_dish(self):
        if not self.menu:
            return None
        return sorted(self.menu)[0]

    def _reserved_total(self):
        total = {}
        for customer in self.customers:
            if customer.get("state", "waiting") in ("waiting", "eating"):
                for kind, count in customer.get("reserved", {}).items():
                    total[kind] = total.get(kind, 0) + int(count)
        return total

    def _dish_available(self, dish):
        if dish not in self.menu:
            return False
        reserved = self._reserved_total()
        for kind, count in self.menu[dish]["recipe"].items():
            usable = self.stock.get(kind, 0) - reserved.get(kind, 0)
            if usable < int(count):
                return False
        return True

    def _cookable_customers(self):
        return [c for c in sort_by_id(self.customers)
                if c.get("state", "waiting") == "waiting"
                and c.get("dish") in self.menu
                and all(self.stock.get(k, 0) >= int(v)
                        for k, v in self.menu[c["dish"]]["recipe"].items())]

    def _interact_stove(self, stove):
        if stove["state"] == "ready":
            if self.hand is not None:
                return []
            dish = stove["dish"]
            stove["state"] = "idle"
            stove["dish"] = None
            stove["cook_ticks_left"] = 0
            stove["ready_ticks"] = 0
            self.hand = dish
            return [("dish_picked", {"stove_id": stove["id"], "dish": dish})]

        if stove["state"] != "idle":
            return []

        customer = next((c for c in self._cookable_customers()
                         if not any(s.get("customer_id") == c["id"] for s in self.stoves)), None)
        if customer is None:
            return []
        dish = customer["dish"]
        recipe = self.menu[dish]["recipe"]
        for kind, count in recipe.items():
            if self.stock.get(kind, 0) < int(count):
                return []
            self.stock[kind] -= int(count)
            if self.stock[kind] == 0:
                del self.stock[kind]
        customer["reserved"] = {}
        stove["state"] = "cooking"
        stove["dish"] = dish
        stove["customer_id"] = customer["id"]
        stove["cook_ticks_left"] = int(round(self.menu[dish]["cook_s"] * TICK))
        stove["ready_ticks"] = 0
        return [("cook_started", {"stove_id": stove["id"], "customer_id": customer["id"], "dish": dish})]

    def _interact_table(self, table):
        if self.hand is None:
            return []
        for customer in sort_by_id(self.customers):
            if customer.get("table_id") != table["id"]:
                continue
            if customer.get("state", "waiting") != "waiting":
                continue
            if customer.get("dish") != self.hand:
                continue
            dish = self.hand
            customer["state"] = "eating"
            customer["eat_ticks_left"] = int(round(self.t["eat_s"] * TICK))
            self.hand = None
            return [("served", {"customer_id": customer["id"], "table_id": table["id"], "dish": dish})]
        return []

    def _spawn_customer(self):
        occupied = {c["table_id"] for c in self.customers}
        free_tables = [t for t in sort_by_id(self.tables) if t["id"] not in occupied]
        if not free_tables:
            return [("no_dish", {"reason": "no_table"})]

        candidates = [dish for dish in sorted(self.menu) if self._dish_available(dish)]
        if not candidates:
            return [("no_dish", {"reason": "no_ingredients"})]

        self._customer_seq += 1
        customer_id = f"C{self._customer_seq}"
        while any(c["id"] == customer_id for c in self.customers):
            self._customer_seq += 1
            customer_id = f"C{self._customer_seq}"
        dish_index = int(self.rng.get("customers").randrange(len(candidates)))
        dish = candidates[dish_index]
        table = free_tables[0]
        recipe = self.menu[dish]["recipe"]
        customer = {
            "id": customer_id,
            "table_id": table["id"],
            "dish": dish,
            "state": "waiting",
            "patience_ticks_left": int(round(self.t["patience_s"] * TICK)),
            "eat_ticks_left": int(round(self.t["eat_s"] * TICK)),
            "reserved": dict(recipe),
        }
        self.ids.reserve(customer_id)
        self.customers.append(customer)
        return [("customer_arrived", {"customer_id": customer_id, "table_id": table["id"], "dish": dish})]

    def _move(self, inp):
        speed = self.t["walk_speed"]
        mx, mz = inp.move
        self.vel = ramp_velocity(self, (mx * speed, mz * speed), int(self.t.get("ramp_max_ticks", 6)))
        b = self.t["bounds"]
        for i, axis in enumerate(("x", "z")):
            self.pos[i] += self.vel[i] / TICK
            lo, hi = b[axis]
            if self.pos[i] <= lo:
                self.pos[i], self.vel[i] = lo, max(0.0, self.vel[i])
            elif self.pos[i] >= hi:
                self.pos[i], self.vel[i] = hi, min(0.0, self.vel[i])
