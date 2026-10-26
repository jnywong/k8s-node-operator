import pluggy
from k8s_autoscaler_plugins.hooks import HookSpec
from k8s_autoscaler_plugins.plugins.always_on.impl import AlwaysOnPlugin

def get_plugin_manager():
    """
    Return plugin manager instance
    """
    # Set up plugin infrastructure
    pm = pluggy.PluginManager("k8sap")
    pm.add_hookspecs(HookSpec)
    pm.register(AlwaysOnPlugin(), name='always-on')

    return pm