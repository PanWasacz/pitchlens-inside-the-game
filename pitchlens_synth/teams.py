"""Fictional teams, rosters and formations.

All clubs and players here are invented for the demo. Any resemblance to real
clubs or people is coincidental.

Formation slots are expressed in a team-relative frame:
  depth: 0 = defensive line, 1 = forward line (scaled by the engine each tick)
  lane:  0..1 across the pitch width
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Slot:
    code: str
    role: str  # GK | DF | MF | FW
    depth: float
    lane: float
    fullback: bool = False


FORMATIONS: dict[str, list[Slot]] = {
    "4-3-3": [
        Slot("GK", "GK", 0.0, 0.5),
        Slot("LB", "DF", 0.0, 0.12, fullback=True),
        Slot("LCB", "DF", 0.0, 0.37),
        Slot("RCB", "DF", 0.0, 0.63),
        Slot("RB", "DF", 0.0, 0.88, fullback=True),
        Slot("LCM", "MF", 0.55, 0.30),
        Slot("DM", "MF", 0.33, 0.50),
        Slot("RCM", "MF", 0.55, 0.70),
        Slot("LW", "FW", 0.95, 0.13),
        Slot("ST", "FW", 1.0, 0.50),
        Slot("RW", "FW", 0.95, 0.87),
    ],
    "4-4-2": [
        Slot("GK", "GK", 0.0, 0.5),
        Slot("LB", "DF", 0.0, 0.12, fullback=True),
        Slot("LCB", "DF", 0.0, 0.37),
        Slot("RCB", "DF", 0.0, 0.63),
        Slot("RB", "DF", 0.0, 0.88, fullback=True),
        Slot("LM", "MF", 0.55, 0.12),
        Slot("LCM", "MF", 0.45, 0.38),
        Slot("RCM", "MF", 0.45, 0.62),
        Slot("RM", "MF", 0.55, 0.88),
        Slot("LS", "FW", 1.0, 0.40),
        Slot("RS", "FW", 1.0, 0.60),
    ],
    "4-2-3-1": [
        Slot("GK", "GK", 0.0, 0.5),
        Slot("LB", "DF", 0.0, 0.12, fullback=True),
        Slot("LCB", "DF", 0.0, 0.37),
        Slot("RCB", "DF", 0.0, 0.63),
        Slot("RB", "DF", 0.0, 0.88, fullback=True),
        Slot("LDM", "MF", 0.32, 0.40),
        Slot("RDM", "MF", 0.32, 0.60),
        Slot("LAM", "MF", 0.72, 0.15),
        Slot("CAM", "MF", 0.70, 0.50),
        Slot("RAM", "MF", 0.72, 0.85),
        Slot("ST", "FW", 1.0, 0.50),
    ],
}


@dataclass(frozen=True)
class PlayerSpec:
    number: int
    name: str


@dataclass
class TeamSpec:
    key: str  # "home" | "away"
    name: str
    short: str
    formation: str
    colors: dict[str, str]
    players: list[PlayerSpec] = field(default_factory=list)

    @property
    def slots(self) -> list[Slot]:
        return FORMATIONS[self.formation]

    def player_id(self, index: int) -> str:
        return f"{self.key[0].upper()}{self.players[index].number:02d}"


# Players are listed in formation-slot order (GK first).
HOME = TeamSpec(
    key="home",
    name="Northbridge Rovers",
    short="NBR",
    formation="4-3-3",
    colors={"primary": "#E63946", "secondary": "#FFFFFF", "goalkeeper": "#FFD23F"},
    players=[
        PlayerSpec(1, "E. Marrowby"),
        PlayerSpec(3, "L. Quennell"),
        PlayerSpec(5, "D. Okonjo"),
        PlayerSpec(6, "S. Haverlund"),
        PlayerSpec(2, "T. Brisco"),
        PlayerSpec(8, "J. Vantreight"),
        PlayerSpec(4, "M. Adeyinka"),
        PlayerSpec(10, "R. Calloway-Fenn"),
        PlayerSpec(11, "K. Ostrander"),
        PlayerSpec(9, "N. Pellegrue"),
        PlayerSpec(7, "A. Duquaine"),
    ],
)

AWAY = TeamSpec(
    key="away",
    name="Kestrel Bay Athletic",
    short="KBA",
    formation="4-4-2",
    colors={"primary": "#3FA7F5", "secondary": "#0B1D3A", "goalkeeper": "#8BE36B"},
    players=[
        PlayerSpec(1, "P. Sandvik-Orr"),
        PlayerSpec(3, "G. Thornquist"),
        PlayerSpec(4, "B. Mwangale"),
        PlayerSpec(5, "C. Delacroix-Hume"),
        PlayerSpec(2, "F. Ilveston"),
        PlayerSpec(11, "Y. Barrowclough"),
        PlayerSpec(6, "H. Nakashiro"),
        PlayerSpec(8, "W. Esterhuy"),
        PlayerSpec(7, "O. Rennick"),
        PlayerSpec(9, "I. Kovalenko-Bray"),
        PlayerSpec(10, "Z. Amberleigh"),
    ],
)
