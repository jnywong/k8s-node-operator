import kopf
from typing import Any, Dict
from k8s_node_operator.base import Node, Nodepool, NodepoolState
from k8s_node_operator.const import PROVIDER_NAME, NODEPOOL_LABELS

# Nodepool allocation target (npat) custom resource

@kopf.on.create('nodepoolallocationtarget') # type: ignore[arg-type]
@kopf.on.update('nodepoolallocationtarget') # type: ignore[arg-type]
async def nodepool_allocation(spec: kopf.Spec, logger: kopf.Logger, k8s_nodes: kopf.Index, **kwargs: Any) -> dict:
    """
    Set minimum node count of selected nodepools. 
    """
    # Parse spec
    label_selector = spec.get('nodepoolSelector', {})
    target_min_node_count = spec.get('plugins', {}).get('alwaysOn', {}).get('minimum', 0)
    # List nodepools that match the node label selector
    node_list = await Node.list_node(label_selector=label_selector, index=k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    status = Nodepool.get_status_list(nodepool_list, NodepoolState.UPDATING.name)
    return status

@kopf.on.delete('nodepoolallocationtarget') # type: ignore[arg-type]
async def delete_nodepool_allocation(spec: kopf.Spec, patch: kopf.Patch, k8s_nodes: kopf.Index, logger: kopf.Logger, **kwargs: Any) -> Nodepool:
    """
    Set minimum node count to 0 on delete.
    """
    label_selector = spec.get('nodepoolSelector', {})
    target_min_node_count = 0
    # List k8s nodepools with node label selector
    node_list = await Node.list_node(label_selector=label_selector, index = k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    for nodepool in nodepool_list:
        if nodepool.min_node_count != nodepool.target_min_node_count:
            logger.debug(f'[{nodepool.name}] Cloud provider minimum node count target state of {nodepool.min_node_count} not reached')
            nodepool = await nodepool.set_min_node_count(target_min_node_count)
        else:
            logger.debug(f'[{nodepool.name}] Cloud provider minimum node count target state of {nodepool.min_node_count} reached')
    return nodepool


@kopf.index('nodes')
def k8s_nodes(body: kopf.Body, labels: kopf.Labels, logger: kopf.Logger, **kwargs: Any) -> dict | None:
    """
    Keep in-memory index of ready k8s nodes to avoid multiple k8s API calls.
    """
    conditions = body['status']['conditions']
    for c in conditions:
        if c['type'] == 'Ready':
            if c['status'] == 'True':
                return {label: value for label, value in labels.items()}
            else:
                raise ValueError('Skipping: node is not ready.')
        else:
            raise KeyError('Condition type "Ready" not found.')
    return None

@kopf.timer('nodepoolallocationtarget', interval=10) # type: ignore[arg-type]
async def reconcile_provider(spec: kopf.Spec, k8s_nodes: kopf.Index, patch: kopf.Patch, logger: kopf.Logger, **kwargs: Any) -> None:
    """
    Regularly reconcile target minimum node count is equal to cloud provider config.
    """
    target_min_node_count = spec.get('plugins', {}).get('alwaysOn', {}).get('minimum', 0)
    label_selector = spec.get('nodepoolSelector', {})
    node_list = await Node.list_node(label_selector=label_selector, index=k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    for nodepool in nodepool_list: # TODO: add timeout error
        if nodepool.min_node_count == nodepool.target_min_node_count:
            logger.info(f'[{nodepool.name}] Cloud provider minimum node count target state of {nodepool.min_node_count} reached')
            state = NodepoolState.READY.name
        else:
            logger.debug(f'[{nodepool.name}] Cloud provider minimum node count target state of {nodepool.min_node_count} not reached')
            await nodepool.set_min_node_count(target_min_node_count)
            state = NodepoolState.UPDATING.name
    status = Nodepool.get_status_list(nodepool_list, state)
    patch.status['nodepool_allocation'] = status

@kopf.timer('nodepoolallocationtarget', interval=10) # type: ignore[arg-type]
async def reconcile_kubernetes(spec: kopf.Spec, k8s_nodes: kopf.Index, patch: kopf.Patch, logger: kopf.Logger, **kwargs: Any) -> None:
    """
    Regularly reconcile target minimum node count is less than or equal to current Kubernetes node count.
    """
    target_min_node_count = spec.get('plugins', {}).get('alwaysOn', {}).get('minimum', {})
    label_selector = spec.get('nodepoolSelector', {})
    node_list = await Node.list_node(label_selector=label_selector, index=k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    for nodepool in nodepool_list:
        if nodepool.target_min_node_count:
            if nodepool.target_min_node_count <= nodepool.current_node_count:
                logger.info(f'[{nodepool.name}] Target minimum node count ({nodepool.target_min_node_count}) <= Kubernetes nodes online ({nodepool.current_node_count}) reached')
                status = Nodepool.get_status_list(nodepool_list, NodepoolState.READY.name)
            else:
                logger.debug(f'[{nodepool.name}] Target minimum node count ({nodepool.target_min_node_count}) <= Kubernetes nodes online ({nodepool.current_node_count}) not reached')
                await nodepool.set_min_node_count(target_min_node_count)
                status = Nodepool.get_status_list(nodepool_list, NodepoolState.UPDATING.name)
    patch.status['nodepool_allocation'] = status
