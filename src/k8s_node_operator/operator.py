import kopf
import os
from typing import Any, Dict
from k8s_node_operator.providers import create_provider, NodepoolState

@kopf.on.create('nodepoolallocationtarget')
@kopf.on.update('nodepoolallocationtarget')
async def nodepool_allocation(spec: kopf.Spec, name: str, namespace: str | None, logger: kopf.Logger, **_: Any) -> Dict:
    # Determine cloud provider
    provider_name = os.environ.get("K8S_NODE_OPERATOR_CLOUD_PROVIDER")
    async with create_provider(name=provider_name, spec=spec, logger=logger) as provider:
        # Set minimum node count
        nodepool = await provider.set_min_node_count(spec.get('minimumNodeCount'))
        logger.info(f"{nodepool=}")
        # Store output in k8s npat object
        return {'state': NodepoolState.READY.name, 'name': nodepool.name, 'node_count': nodepool.current_node_count, 'min_node_count': nodepool.min_node_count, 'max_node_count': nodepool.max_node_count, 'target_min_node_count': nodepool.target_min_node_count}

@kopf.on.delete('nodepoolallocationtarget')
async def delete_nodepool_allocation(spec: kopf.Spec, logger: kopf.Logger, **_: Any) -> None:
    # Set minimum node count to zero
    target_min_node_count = 0
    provider_name = os.environ.get("K8S_NODE_OPERATOR_CLOUD_PROVIDER")
    async with create_provider(name=provider_name, spec=spec, logger=logger) as provider:
        nodepool = await provider.set_min_node_count(target_min_node_count=target_min_node_count)
        logger.info(f'npat deleted: "{nodepool.name}" minimum node count set to {nodepool.min_node_count}.')