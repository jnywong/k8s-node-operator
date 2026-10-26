from k8s_autoscaler_plugins.hooks import hookimpl

class AlwaysOnPlugin:
    @hookimpl
    def always_on_scaling(self, logger):
        logger.warning('hello world!')