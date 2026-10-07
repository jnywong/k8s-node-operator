from enum import Enum

class NodepoolState(Enum):
    """
    An enumerated list of nodepool states.
    """
    READY = 1
    UPDATING = 2
    ERROR = 3
