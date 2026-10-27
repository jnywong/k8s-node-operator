"""
Define hook specs for autoscaler plugins using Pluggy.
"""

import pluggy

hookspec = pluggy.HookspecMarker("k8sap")
hookimpl = pluggy.HookimplMarker("k8sap")

class HookSpec:
    @hookspec
    def evaluate_nodepool(logger):
        """
        Evaluate nodepool object and update target_min_node_count.
        """