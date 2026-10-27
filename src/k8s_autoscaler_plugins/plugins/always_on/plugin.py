from k8s_autoscaler_plugins.hooks import hookimpl

class AlwaysOnPlugin:
    @hookimpl
    def evaluate_nodepool(self, logger):
        logger.warning('hello world!')