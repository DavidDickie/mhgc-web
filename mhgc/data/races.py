"""Races (empires).  MHGC races have no innate traits: every empire starts the same (gcugen.c),
so "race data" is just naming and the empire kinds.

- Empire 0 is the independents ("Rebels"): unowned systems, rebelled systems and rebel militia
  (gcrun.c:574-617).  It gives no orders and is never ranked.
- Empires 1..16 each get a home position on the map; humans take seats, NPRs fill the rest.
"""
from .constants import DEFAULT_RACE_NAMES, INDEPENDENT, INDEPENDENT_NAME, MAX_EMPIRES, RACE_NAME_MAX

KINDS = ("human", "npr", "independent", "dead")

__all__ = ["DEFAULT_RACE_NAMES", "INDEPENDENT", "INDEPENDENT_NAME", "MAX_EMPIRES",
           "RACE_NAME_MAX", "KINDS"]
