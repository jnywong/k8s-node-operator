import kopf
import os
from typing import Any, Dict
from k8s_autoscaler_plugins.providers import create_provider

# Nodepool allocation target (npat) custom resource

@kopf.on.create('nodepoolallocationtarget')
@kopf.on.update('nodepoolallocationtarget')
async def nodepool_allocation(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> Dict:
    """
    Set minimum node count on create or update.
    """
    target_min_node_count = spec.get('minimumNodeCount')
    # Determine cloud provider
    provider_name = os.environ.get("K8S_NODE_OPERATOR_CLOUD_PROVIDER", "")
    async with create_provider(name=provider_name, spec=spec, npat_name=name, logger=logger) as provider:
        # Set minimum node count
        nodepool = await provider.set_min_node_count(target_min_node_count=target_min_node_count)
        # Store result in k8s npat object
        patch.status['state'] = nodepool.state
        return {'name': nodepool.name, 'min_node_count': nodepool.min_node_count, 'max_node_count': nodepool.max_node_count, 'target_min_node_count': nodepool.target_min_node_count}

@kopf.on.delete('nodepoolallocationtarget')
async def delete_nodepool_allocation(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> None:
    """
    Set minimum node count to zero on delete.
    """
    target_min_node_count = 0
    provider_name = os.environ.get("K8S_NODE_OPERATOR_CLOUD_PROVIDER", "")
    async with create_provider(name=provider_name, spec=spec, npat_name=name, logger=logger) as provider:
        nodepool = await provider.set_min_node_count(target_min_node_count=target_min_node_count)
        logger.info(f'npat deleted: "{nodepool.name}" minimum node count set to {nodepool.min_node_count}.')

# Reconciliation loop

@kopf.index('nodes')
def k8s_nodes(body: kopf.Body, labels: kopf.Labels, name: str, logger: kopf.Logger, **_: Any) -> Any:
    """
    Keep in-memory index of ready k8s nodes to avoid multiple k8s API calls.
    """
    conditions = body['status']['conditions']
    for c in conditions:
        if c['type'] == 'Ready':
            if c['status'] == 'True':
                return {label: value for label, value in labels.items()}

@kopf.timer('nodepoolallocationtarget', interval=60) # type: ignore[arg-type]
def count_k8s_nodes(spec: kopf.Spec, name: str, k8s_nodes: kopf.Index, patch: kopf.Patch, logger: kopf.Logger, **kwargs: Any) -> None:
    """
    Regularly calculate and save the *actual state* from an in-memory index of the k8s nodes. TODO: additional kopf.timers can be added to calculate actual state of interest of plugins, e.g. memory utilization.
    """
    label_name = spec.get('nodepoolLabelName', '')
    label_value = spec.get('nodepoolLabelValue', '')
    ready_nodes: Any = k8s_nodes.get(label_name, [])
    current_node_count = len([label_value for n in ready_nodes if label_value == n])
    patch.status['current_node_count'] = current_node_count

# @kopf.on.event('nodepoolallocationtarget')
# def react_on_state_changes(body: kopf.Body, name: str, **_: Any) -> None:
#     ... # This is where reconciliation between target condition of plugin trigger and actual state will happen for level-based triggering https://docs.kopf.dev/en/stable/reconciliation/#level-based-triggering.
