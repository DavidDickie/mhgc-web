"""Static game data: technologies, ship/troop types, artifacts and constants."""
from .techs import TECHS, FUTURE_TECH, Tech, tech_vp, all_prereqs, missing_prereqs  # noqa: F401
from .ships import SHIP_TYPES, ShipType, SCOUT_CLASSES, NONWAR_CLASSES, LINE_TYPES  # noqa: F401
from .troops import TROOP_TYPES, TroopType  # noqa: F401
from .artifacts import ARTIFACTS, Artifact  # noqa: F401
from . import constants  # noqa: F401
