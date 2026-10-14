import kopf
import os
from typing import Any, Dict
from k8s_node_operator.base import Node, Nodepool, NodepoolState

# Nodepool allocation target (npat) custom resource

PROVIDER_NAME = os.environ.get('K8S_NODE_OPERATOR_CLOUD_PROVIDER', '')

@kopf.on.create('nodepoolallocationtarget')
@kopf.on.update('nodepoolallocationtarget')
async def nodepool_allocation(spec: kopf.Spec, k8s_nodes: kopf.Index, memo: kopf.Memo, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> Dict:
    """
    Set minimum node count of selected nodepools. 
    """
    # Parse spec
    label_selector = spec.get('nodeSelector')
    target_min_node_count = spec.get('minimumNodeCount')
    if not target_min_node_count: # Spec 'minimumNodeCount: 0' returns None, so set this to integer value 0 explicitly if needed
        target_min_node_count = 0 
    # List nodepools that match the node label selector
    node_list = await Node.list_node(label_selector=label_selector, index=k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    # Set nodepool minimum node count
    for nodepool in nodepool_list:
        await nodepool.set_min_node_count(target_min_node_count)
    status = Nodepool.get_status_list(nodepool_list)
    return status

@kopf.on.delete('nodepoolallocationtarget')
async def delete_nodepool_allocation(spec: kopf.Spec, patch: kopf.Patch, k8s_nodes: kopf.Index, logger: kopf.Logger, **_: Any) -> None:
    """
    Set minimum node count to zero on delete.
    """
    label_selector = spec.get('nodeSelector')
    target_min_node_count = 0
    # List k8s nodepools with node label selector
    node_list = await Node.list_node(label_selector=label_selector, index = k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, target_min_node_count)
    # Set nodepool minimum node count
    for nodepool in nodepool_list:
        await nodepool.set_min_node_count(target_min_node_count)
        logger.info(f'npat deleted: "{nodepool.name}" minimum node count set to {nodepool.target_min_node_count}.')


@kopf.index('nodes')
def k8s_nodes(body: kopf.Body, labels: kopf.Labels, logger: kopf.Logger, **_: Any) -> dict:
    """
    Keep in-memory index of ready k8s nodes to avoid multiple k8s API calls.
    """
    conditions = body['status']['conditions']
    for c in conditions:
        if c['type'] == 'Ready':
            if c['status'] == 'True':
                return {label: value for label, value in labels.items()}

@kopf.timer('nodepoolallocationtarget', interval=60) # type: ignore[arg-type]
async def reconcile_k8s_nodes(spec: kopf.Spec, status: kopf.Status, name: str, k8s_nodes: kopf.Index, patch: kopf.Patch, logger: kopf.Logger, **kwargs: Any) -> None:
    """
    Regularly reconcile node count current state with target state.
    """
    min_node_count = spec.get('minimumNodeCount')
    label_selector = spec.get('nodeSelector')
    node_list = await Node.list_node(label_selector=label_selector, index=k8s_nodes)
    nodepool_list = await Nodepool.list_nodepool(node_list, min_node_count)
    for nodepool in nodepool_list:
        nodepool.current_node_count = nodepool.get_current_node_count(node_list)
        if nodepool.target_min_node_count:
            if nodepool.current_node_count >= nodepool.target_min_node_count:
                logger.info('Target state reached')
                nodepool.state = NodepoolState.READY.name
            else:
                logger.debug('Target state not reached')
                nodepool.state = NodepoolState.UPDATING.name
    status = Nodepool.get_status_list(nodepool_list)
    patch.status['nodepool_allocation'] = status