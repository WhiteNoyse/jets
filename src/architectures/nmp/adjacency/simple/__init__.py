from .learned import LEARNED_ADJACENCIES
from .constant import CONSTANT_ADJACENCIES
from .physics import PHYSICS_ADJACENCIES

SIMPLE_ADJACENCIES = {}
SIMPLE_ADJACENCIES.update(LEARNED_ADJACENCIES)
SIMPLE_ADJACENCIES.update(CONSTANT_ADJACENCIES)
SIMPLE_ADJACENCIES.update(PHYSICS_ADJACENCIES)
