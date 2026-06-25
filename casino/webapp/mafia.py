"""Мультиплеер «Ночи 11A» — мафия в неон-городе.

Комнаты по коду: хост создаёт, друзья заходят по коду, хост может добить ботами
и стартовать. Роли раздаются рандомно. Цикл: Ночь (роли ходят) → День (СХОДКА в
Кальянной Коли: голосуем, кого выгнать). До 7 ночей. Город побеждает, выбив всю
мафию; мафия — пережив 7 ночей или сравнявшись числом с городом.

Здесь только чистая игровая логика + менеджер комнат с фоновым тиком фаз.
Сетевой слой (WebSocket) — в server.py.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger("casino.mafia")

# роли
MAFIA = "mafia"
DOCTOR = "doctor"
DETECTIVE = "detective"
CIVILIAN = "civilian"

ROLE_RU = {
    MAFIA: "Мафия 🎩", DOCTOR: "Доктор 💨", DETECTIVE: "Комиссар 💻", CIVILIAN: "Мирный 👤",
}

# персонажи-аватары (банда «11A»)
CHARS = ["matin", "gorila", "samira", "rusik", "baran", "pastuh", "gryaz", "dima", "kolya"]

# дома/локации на карте города (x,y — проценты по картинке карты)
HOUSES = [
    {"id": "otel",     "name": "Отель",     "emoji": "🏨", "x": 50, "y": 11},
    {"id": "aero",     "name": "Аэропорт",  "emoji": "✈️", "x": 80, "y": 19},
    {"id": "magaz",    "name": "Магазин",   "emoji": "🏪", "x": 21, "y": 29},
    {"id": "park",     "name": "Парк",      "emoji": "🌳", "x": 73, "y": 41},
    {"id": "hata",     "name": "Хата",      "emoji": "🏠", "x": 30, "y": 52},
    {"id": "kopeyka",  "name": "Копейка",   "emoji": "🚗", "x": 63, "y": 62},
    {"id": "pole",     "name": "Поле",      "emoji": "🌾", "x": 19, "y": 71},
    {"id": "skameyka", "name": "Скамейка",  "emoji": "🪑", "x": 79, "y": 79},
    {"id": "svalka",   "name": "Свалка",    "emoji": "🗑️", "x": 41, "y": 88},
]

MAX_NIGHTS = 7


@dataclass
class Player:
    id: int
    name: str
    bot: bool = False
    role: str = CIVILIAN
    alive: bool = True
    char: str = ""                       # выбранный персонаж-аватар
    house: str = ""                      # выбранная локация на карте
    # действия текущей фазы
    night_target: Optional[int] = None   # цель мафии/доктора/комиссара
    vote: Optional[int] = None           # дневной голос
    checked: bool = False                # комиссар уже проверял этой ночью


def roles_for(n: int) -> List[str]:
    """Раскладка ролей под число игроков."""
    mafia = max(1, n // 4)
    roles = [MAFIA] * mafia
    if n >= 4:
        roles.append(DOCTOR)
    if n >= 5:
        roles.append(DETECTIVE)
    roles += [CIVILIAN] * (n - len(roles))
    return roles[:n]


@dataclass
class MafiaRoom:
    code: str
    host_id: int
    night_sec: int = 30
    day_sec: int = 60
    city_sec: int = 25
    players: Dict[int, Player] = field(default_factory=dict)
    phase: str = "lobby"                  # lobby | night | day | ended
    night: int = 0
    phase_ends: float = 0.0               # time.monotonic()
    winner: Optional[str] = None          # city | mafia
    log: List[str] = field(default_factory=list)
    last_killed: Optional[int] = None
    detective_result: Optional[dict] = None  # {by, target, is_mafia}
    subs: set = field(default_factory=set)

    # --- участники ---

    def order(self) -> List[Player]:
        return list(self.players.values())

    def alive_players(self) -> List[Player]:
        return [p for p in self.players.values() if p.alive]

    def alive_mafia(self) -> List[Player]:
        return [p for p in self.alive_players() if p.role == MAFIA]

    def add_player(self, pid: int, name: str, bot: bool = False) -> bool:
        if self.phase != "lobby" or pid in self.players:
            return False
        self.players[pid] = Player(id=pid, name=name, bot=bot)
        return True

    def add_bots(self, n: int) -> int:
        added = 0
        i = 1
        while added < n and len(self.players) < 15:
            bid = -1000 - len(self.players)
            while bid in self.players:
                bid -= 1
            self.players[bid] = Player(id=bid, name=f"Бот-{_BOT_NAMES[i % len(_BOT_NAMES)]}",
                                       bot=True, char=random.choice(CHARS))
            added += 1; i += 1
        return added

    def set_char(self, pid: int, char: str) -> bool:
        p = self.players.get(pid)
        if not p or self.phase not in ("lobby", "city") or char not in CHARS:
            return False
        p.char = char
        return True

    def set_house(self, pid: int, house: str) -> bool:
        p = self.players.get(pid)
        if not p or self.phase != "city" or house not in {h["id"] for h in HOUSES}:
            return False
        p.house = house
        return True

    def remove(self, pid: int) -> None:
        self.players.pop(pid, None)

    # --- старт ---

    def can_start(self) -> bool:
        return self.phase == "lobby" and len(self.players) >= 4

    def start(self) -> bool:
        if not self.can_start():
            return False
        roles = roles_for(len(self.players))
        random.shuffle(roles)
        for p, r in zip(self.players.values(), roles):
            p.role = r; p.alive = True
        for p in self.players.values():
            if not p.char:
                p.char = random.choice(CHARS)
        self.log = ["🌃 Банда заходит в город «11A». Выбери, куда пойти на карте…"]
        self._begin_city()
        return True

    def _begin_city(self) -> None:
        self.phase = "city"
        self.phase_ends = time.monotonic() + self.city_sec
        self._bots_city()

    def _bots_city(self) -> None:
        free = [h["id"] for h in HOUSES]
        random.shuffle(free)
        for b in [p for p in self.players.values() if p.bot and not p.house]:
            b.house = free.pop() if free else random.choice([h["id"] for h in HOUSES])

    def _begin_night(self) -> None:
        self.night += 1
        self.phase = "night"
        self.phase_ends = time.monotonic() + self.night_sec
        self.last_killed = None
        self.detective_result = None
        for p in self.players.values():
            p.night_target = None; p.checked = False
        self._bots_night()

    def _begin_day(self) -> None:
        self.phase = "day"
        self.phase_ends = time.monotonic() + self.day_sec
        for p in self.players.values():
            p.vote = None
        self._bots_day()

    # --- ночные действия ---

    def set_night_target(self, pid: int, target: int) -> bool:
        p = self.players.get(pid)
        tgt = self.players.get(target)
        if self.phase != "night" or not p or not p.alive or not tgt or not tgt.alive:
            return False
        if p.role not in (MAFIA, DOCTOR, DETECTIVE):
            return False
        if p.role == MAFIA and tgt.role == MAFIA:
            return False
        p.night_target = target
        if p.role == DETECTIVE:
            p.checked = True
            self.detective_result = {"by": pid, "target": target,
                                     "is_mafia": tgt.role == MAFIA}
        return True

    def _resolve_night(self) -> None:
        # цель мафии — самая частая среди живых мафиози
        mafia_votes = [p.night_target for p in self.alive_mafia() if p.night_target]
        victim_id = _most_common(mafia_votes)
        # доктор лечит
        heals = {p.night_target for p in self.alive_players()
                 if p.role == DOCTOR and p.night_target}
        if victim_id and victim_id not in heals:
            v = self.players.get(victim_id)
            if v and v.alive:
                v.alive = False
                self.last_killed = victim_id
                self.log.append(f"🌙 Ночью убили: {v.name}")
        if self.last_killed is None:
            self.log.append("🌙 Ночь прошла спокойно — никто не погиб.")

    # --- дневное голосование ---

    def set_vote(self, pid: int, target: int) -> bool:
        p = self.players.get(pid)
        tgt = self.players.get(target)
        if self.phase != "day" or not p or not p.alive or not tgt or not tgt.alive:
            return False
        p.vote = target
        return True

    def _resolve_day(self) -> None:
        votes = [p.vote for p in self.alive_players() if p.vote]
        out_id = _most_common(votes)
        if out_id:
            v = self.players.get(out_id)
            if v and v.alive:
                v.alive = False
                self.log.append(f"☀️ СХОДКА выгнала: {v.name} (был {ROLE_RU[v.role]})")
        else:
            self.log.append("☀️ Город не определился — никого не выгнали.")

    # --- проверка победы / тик фаз ---

    def _check_winner(self) -> Optional[str]:
        m = len(self.alive_mafia())
        c = len(self.alive_players()) - m
        if m == 0:
            return "city"
        if m >= c:
            return "mafia"
        return None

    def tick(self) -> bool:
        """Двигает фазу, если истёк таймер. True — если состояние изменилось."""
        if self.phase in ("lobby", "ended"):
            return False
        if time.monotonic() < self.phase_ends:
            return False
        if self.phase == "city":
            self._begin_night()
            return True
        if self.phase == "night":
            self._resolve_night()
            w = self._check_winner()
            if w:
                return self._end(w)
            self._begin_day()
        elif self.phase == "day":
            self._resolve_day()
            w = self._check_winner()
            if w:
                return self._end(w)
            if self.night >= MAX_NIGHTS:
                return self._end("mafia")  # не успели за 7 ночей
            self._begin_night()
        return True

    def _end(self, winner: str) -> bool:
        self.phase = "ended"
        self.winner = winner
        self.log.append("🏆 Город спасён — мафия выбита!" if winner == "city"
                        else "💀 Мафия захватила город «11A».")
        return True

    # --- боты ---

    def _bots_night(self) -> None:
        alive = self.alive_players()
        for b in [p for p in alive if p.bot]:
            if b.role == MAFIA:
                cand = [p.id for p in alive if p.role != MAFIA]
            elif b.role == DOCTOR:
                cand = [p.id for p in alive]
            elif b.role == DETECTIVE:
                cand = [p.id for p in alive if p.id != b.id]
            else:
                continue
            if cand:
                self.set_night_target(b.id, random.choice(cand))

    def _bots_day(self) -> None:
        alive = self.alive_players()
        for b in [p for p in alive if p.bot]:
            cand = [p.id for p in alive if p.id != b.id]
            # мафия-бот не голосует за своих
            if b.role == MAFIA:
                cand = [pid for pid in cand if self.players[pid].role != MAFIA] or cand
            if cand:
                b.vote = random.choice(cand)

    # --- снимок для клиента ---

    def snapshot(self, viewer: Optional[int] = None) -> dict:
        me = self.players.get(viewer) if viewer is not None else None
        ends_in = max(0.0, self.phase_ends - time.monotonic()) if self.phase in ("city", "night", "day") else 0.0
        show_roles = self.phase == "ended"
        check = None
        if me and me.role == DETECTIVE and self.detective_result and self.detective_result["by"] == me.id:
            t = self.players.get(self.detective_result["target"])
            check = {"name": t.name if t else "?", "isMafia": self.detective_result["is_mafia"]}
        players = []
        for p in self.order():
            # роль видна: себе; мафии — других мафиози; всем — в конце
            role_vis = None
            if show_roles or (me and (p.id == me.id or (me.role == MAFIA and p.role == MAFIA))):
                role_vis = p.role
            players.append({
                "id": p.id, "name": p.name, "bot": p.bot, "alive": p.alive,
                "role": role_vis, "roleRu": ROLE_RU.get(role_vis) if role_vis else None,
                "char": p.char, "house": p.house,
            })
        return {
            "type": "mafia", "code": self.code, "phase": self.phase,
            "night": self.night, "maxNights": MAX_NIGHTS, "endsIn": round(ends_in, 1),
            "hostId": self.host_id, "winner": self.winner, "log": self.log[-8:],
            "you": viewer, "yourRole": me.role if me else None,
            "yourRoleRu": ROLE_RU.get(me.role) if me else None,
            "yourTarget": me.night_target if me else None,
            "yourVote": me.vote if me else None,
            "yourChar": me.char if me else None,
            "yourHouse": me.house if me else None,
            "check": check, "houses": HOUSES, "chars": CHARS,
            "players": players, "canStart": self.can_start(),
        }


_BOT_NAMES = ["Гена", "Толик", "Вован", "Жора", "Лёха", "Стас", "Витёк", "Колян",
              "Серый", "Дрон", "Макс", "Рома"]


def _most_common(items: list):
    if not items:
        return None
    best, n = None, 0
    for it in set(items):
        c = items.count(it)
        if c > n:
            best, n = it, c
    return best


def gen_code() -> str:
    return "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))


class MafiaManager:
    def __init__(self):
        self._rooms: Dict[str, MafiaRoom] = {}
        self._task: Optional[asyncio.Task] = None

    def create(self, host_id: int, name: str) -> MafiaRoom:
        code = gen_code()
        while code in self._rooms:
            code = gen_code()
        room = MafiaRoom(code=code, host_id=host_id)
        room.add_player(host_id, name)
        self._rooms[code] = room
        return room

    def get(self, code: str) -> Optional[MafiaRoom]:
        return self._rooms.get((code or "").upper())

    def room_of(self, pid: int) -> Optional[MafiaRoom]:
        for r in self._rooms.values():
            if pid in r.players:
                return r
        return None

    def start_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        last_sync = 0.0
        while True:
            try:
                await asyncio.sleep(0.25)
                now = time.monotonic()
                for room in list(self._rooms.values()):
                    changed = room.tick()
                    if changed:
                        await self._broadcast(room)
                    elif room.phase in ("night", "day") and now - last_sync >= 1.0:
                        await self._broadcast(room, light=True)
                # подчистка завершённых/пустых комнат
                for code in [c for c, r in self._rooms.items()
                             if not r.players or (r.phase == "ended" and now - r.phase_ends > 120)]:
                    self._rooms.pop(code, None)
                if now - last_sync >= 1.0:
                    last_sync = now
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.debug("mafia loop error", exc_info=True)

    async def broadcast(self, room: MafiaRoom) -> None:
        await self._broadcast(room)

    async def _broadcast(self, room: MafiaRoom, light: bool = False) -> None:
        for ws in list(room.subs):
            if getattr(ws, "closed", True):
                room.subs.discard(ws); continue
            try:
                viewer = getattr(ws, "_uid", None)
                if light:
                    await ws.send_json({"type": "mafia_timer",
                                        "endsIn": round(max(0.0, room.phase_ends - time.monotonic()), 1),
                                        "phase": room.phase})
                else:
                    await ws.send_json(room.snapshot(viewer))
            except (ConnectionResetError, RuntimeError):
                room.subs.discard(ws)
