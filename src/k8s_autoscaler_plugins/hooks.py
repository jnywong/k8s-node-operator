"""
Define hook specs for autoscaler plugins using Pluggy.
"""

import pluggy

hookspec = pluggy.HookspecMarker("k8sap")
hookimpl = pluggy.HookimplMarker("k8sap")

class HookSpec:
    @hookspec
    def aggregator(logger):
        """
        Aggregate plugins.
        """
