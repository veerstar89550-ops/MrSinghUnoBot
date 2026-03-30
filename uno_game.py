import random

COLORS = ['red', 'yellow', 'green', 'blue']
COLOR_EMOJI = {'red': '🔴', 'yellow': '🟡', 'green': '🟢', 'blue': '🔵'}


def card_display(card: str) -> str:
    if card == 'wild':
        return '🌈 Wild'
    if card == 'wild4':
        return '🌈 +4'
    color, value = card.split('_', 1)
    e = COLOR_EMOJI[color]
    if value == 'skip':
        return f'{e} Skip'
    if value == 'reverse':
        return f'{e} Rev'
    if value == 'draw2':
        return f'{e} +2'
    return f'{e} {value}'


def card_points(card: str) -> int:
    if 'wild' in card:
        return 50
    _, v = card.split('_', 1)
    if v in ('skip', 'reverse', 'draw2'):
        return 20
    return int(v)


def make_deck() -> list:
    deck = []
    for c in COLORS:
        deck.append(f'{c}_0')
        for n in range(1, 10):
            deck += [f'{c}_{n}'] * 2
        for a in ['skip', 'reverse', 'draw2']:
            deck += [f'{c}_{a}'] * 2
    deck += ['wild'] * 4
    deck += ['wild4'] * 4
    random.shuffle(deck)
    return deck


def can_play(card: str, current_color: str, top_card: str | None) -> bool:
    if 'wild' in card:
        return True
    c, v = card.split('_', 1)
    if c == current_color:
        return True
    if top_card and '_' in top_card:
        _, tv = top_card.split('_', 1)
        if v == tv:
            return True
    return False


class UnoGame:
    def __init__(self, chat_id: int, creator_id: int, creator_name: str):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.state = 'waiting'          # waiting | playing | finished
        self.players: list[tuple] = []  # [(user_id, name), ...]
        self.hands: dict = {}           # uid -> [cards]
        self.deck: list = []
        self.discard: list = []
        self.current_color: str = ''
        self.current_idx: int = 0
        self.direction: int = 1         # 1 = clockwise, -1 = reverse
        self.uno_safe: set = set()      # uids who called UNO with 1 card
        self.scores: dict = {}          # uid -> cumulative points
        self.wins: dict = {}            # uid -> win count
        self.names: dict = {}           # uid -> display name
        self._add(creator_id, creator_name)

    # ── Player management ──────────────────────────────────────────────────

    def _add(self, uid: int, name: str):
        self.players.append((uid, name))
        self.scores.setdefault(uid, 0)
        self.wins.setdefault(uid, 0)
        self.names[uid] = name

    def join(self, uid: int, name: str) -> str:
        if uid in {u for u, _ in self.players}:
            return 'already'
        if len(self.players) >= 10:
            return 'full'
        self._add(uid, name)
        return 'ok'

    # ── Game flow ──────────────────────────────────────────────────────────

    def start(self) -> bool:
        if len(self.players) < 2:
            return False
        self.state = 'playing'
        self.deck = make_deck()
        self.hands = {uid: [] for uid, _ in self.players}
        for _ in range(7):
            for uid, _ in self.players:
                self.hands[uid].append(self.deck.pop())
        # First card must not be wild
        while True:
            card = self.deck.pop()
            if 'wild' not in card:
                break
            self.deck.insert(0, card)
        self.discard = [card]
        self.current_color = card.split('_')[0]
        self.current_idx = 0
        self.direction = 1
        return True

    @property
    def top_card(self) -> str | None:
        return self.discard[-1] if self.discard else None

    def current_player(self) -> tuple:
        return self.players[self.current_idx]

    def _advance(self, steps: int = 1):
        n = len(self.players)
        self.current_idx = (self.current_idx + self.direction * steps) % n

    def draw(self, uid: int, count: int = 1) -> list:
        drawn = []
        for _ in range(count):
            if not self.deck:
                top = self.discard.pop()
                self.deck = self.discard
                random.shuffle(self.deck)
                self.discard = [top]
            if self.deck:
                c = self.deck.pop()
                self.hands[uid].append(c)
                drawn.append(c)
        return drawn

    def play(self, uid: int, card: str, chosen_color: str | None = None) -> dict:
        if uid != self.current_player()[0]:
            return {'result': 'not_your_turn'}
        if card not in self.hands.get(uid, []):
            return {'result': 'invalid'}
        if not can_play(card, self.current_color, self.top_card):
            return {'result': 'cannot_play'}

        self.hands[uid].remove(card)
        self.discard.append(card)
        self.uno_safe.discard(uid)

        if not self.hands[uid]:
            pts = self._award(uid)
            self.state = 'finished'
            return {'result': 'win', 'points': pts}

        info = {'result': 'ok', 'effect': None, 'affected_uid': None,
                'affected_name': None, 'drawn': []}

        if 'wild' in card:
            self.current_color = chosen_color or 'red'
            if card == 'wild4':
                self._advance()
                t_uid = self.current_player()[0]
                drawn = self.draw(t_uid, 4)
                info.update({'effect': 'draw4', 'affected_uid': t_uid,
                              'affected_name': self.names.get(t_uid), 'drawn': drawn})
                self._advance()
            else:
                info['effect'] = 'wild'
                self._advance()

        else:
            c, v = card.split('_', 1)
            self.current_color = c

            if v == 'skip':
                self._advance(2)
                info['effect'] = 'skip'

            elif v == 'reverse':
                self.direction *= -1
                if len(self.players) == 2:
                    self._advance(2)  # acts like skip in 2-player
                else:
                    self._advance()
                info['effect'] = 'reverse'

            elif v == 'draw2':
                self._advance()
                t_uid = self.current_player()[0]
                drawn = self.draw(t_uid, 2)
                info.update({'effect': 'draw2', 'affected_uid': t_uid,
                              'affected_name': self.names.get(t_uid), 'drawn': drawn})
                self._advance()

            else:
                self._advance()

        return info

    # ── Scoring ────────────────────────────────────────────────────────────

    def _award(self, winner_id: int) -> int:
        pts = sum(
            card_points(c)
            for uid, _ in self.players
            if uid != winner_id
            for c in self.hands.get(uid, [])
        )
        self.scores[winner_id] = self.scores.get(winner_id, 0) + pts
        self.wins[winner_id] = self.wins.get(winner_id, 0) + 1
        return pts

    def leaderboard(self) -> list[dict]:
        rows = []
        for uid, _ in self.players:
            rows.append({
                'uid': uid,
                'name': self.names.get(uid, 'Unknown'),
                'score': self.scores.get(uid, 0),
                'wins': self.wins.get(uid, 0),
                'cards': len(self.hands.get(uid, [])),
            })
        return sorted(rows, key=lambda x: x['score'], reverse=True)

    # ── UNO catch system ───────────────────────────────────────────────────

    def catch_uno(self, reporter_id: int) -> tuple[bool, str | None]:
        """
        Returns (caught, target_name) — caught=True if penalty was applied.
        Checks all opponents who have exactly 1 card and haven't called UNO.
        """
        for uid, name in self.players:
            if uid != reporter_id:
                if len(self.hands.get(uid, [])) == 1 and uid not in self.uno_safe:
                    self.draw(uid, 2)
                    return True, name
        return False, None
