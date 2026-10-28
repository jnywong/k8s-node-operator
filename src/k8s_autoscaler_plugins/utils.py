import pluggy
import k8s_autoscaler_plugins.hooks as hookspec

def get_plugin_manager():
    """
    Get the plugin manager instance.
    """
    # Set up plugin infrastructure
    pm = pluggy.PluginManager("k8s-autoscaler-plugins")
    pm.add_hookspecs(hookspec)
    # Automatically register installed plugins with plugin entrypoint
    pm.load_setuptools_entrypoints('k8s-autoscaler-plugins')
    return pm