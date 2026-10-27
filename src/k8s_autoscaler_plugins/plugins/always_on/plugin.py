import kopf
from k8s_autoscaler_plugins.base import Nodepool
from k8s_autoscaler_plugins.hooks import hookimpl

class AlwaysOnPlugin:
    @hookimpl
    def evaluate_nodepool(self, nodepool: Nodepool, spec: kopf.Spec, logger: kopf.Logger) -> Nodepool:
        target_min_node_count = spec.get('plugins', {}).get('alwaysOn', {}).get('minimum', 0)
        if nodepool.target_min_node_count <= target_min_node_count:
            nodepool.target_min_node_count = target_min_node_count
        else:
            logger.info(f'Spec {target_min_node_count=} < current {nodepool.target_min_node_count=}')
        logger.info(f'[plugin] {self.__class__.__name__} succeeded')
        return nodepool