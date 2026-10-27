"""
Define hook specs for autoscaler plugins using Pluggy.
"""

import kopf
import pluggy
from k8s_autoscaler_plugins.base import Nodepool

hookspec = pluggy.HookspecMarker("k8sap")
hookimpl = pluggy.HookimplMarker("k8sap")

class HookSpec:
    @hookspec
    def evaluate_nodepool(nodepool: Nodepool, spec: kopf.Spec, logger: kopf.Logger):
        """
        Evaluate nodepool object and update target_min_node_count.
        """