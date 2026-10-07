import kopf
from collections import Counter
from kubernetes.utils import quantity
from typing import Any, Dict
from k8s_autoscaler_plugins.base import NodepoolState

# Nodepool utilization threshold (nput) custom resource

@kopf.on.create('nodepoolutilizationthreshold')
@kopf.on.update('nodepoolutilizationthreshold')
async def nodepool_utilization(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> Dict:
    """
    Get current utilization on create or update.
    """
    patch.status['state'] = NodepoolState.READY.name


# @kopf.on.delete('nodepoolutilizationthreshold')
# async def delete_nodepool_utilization(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> None:
#     """
#     Delete npat child resource. See https://docs.kopf.dev/en/stable/hierarchies/#owner-references for how to mark ownership of child resources.
#     """

# Reconciliation loop

@kopf.index('nodes')
def k8s_nodes_allocatable(body: kopf.Body, labels: kopf.Labels, name: str, logger: kopf.Logger, **_: Any) -> Any:
    """
    Keep in-memory index of total resources allocatable of ready k8s nodes to avoid multiple k8s API calls.
    """
    conditions = body['status']['conditions']
    allocatable = body['status']['allocatable']
    node_name = body['metadata']['name']
    for c in conditions:
        if c['type'] == 'Ready':
            if c['status'] == 'True':
                return {(label, value): {'node_name': node_name, 'allocatable': allocatable} for label, value in labels.items()}

@kopf.index('pods')
def k8s_nodes_requests(body: kopf.Body, labels: kopf.Labels, name: str, logger: kopf.Logger, **_: Any) -> Any:
    """
    Keep in-memory index of total resource requests of pods on node to avoid multiple k8s API calls.
    """
    requests = []
    containers = body['spec']['containers']
    for container in containers:
        requests.append(container['resources']['requests'])
    node_name = body['spec']['nodeName']
    return {node_name: requests}


@kopf.timer('nodepoolutilizationthreshold', interval=60) # type: ignore[arg-type]
def calculate_k8s_nodepool_utilization(spec: kopf.Spec, name: str, k8s_nodes_allocatable: kopf.Index, k8s_nodes_requests: kopf.Index, patch: kopf.Patch, logger: kopf.Logger, digits=2, **kwargs: Any) -> float:
    label_name = spec.get('nodepoolLabelName', '')
    label_value = spec.get('nodepoolLabelValue', '')
    resource = spec.get('policy').get('type')
    # utilization = sum(requests) / sum(allocatable)
    requests = get_nodepool_resource_requests(k8s_nodes_requests, resource, logger)
    allocatable = get_nodepool_allocatable_resource(k8s_nodes_allocatable, label_name, label_value, resource)
    utilization = sum([v for _, v in requests.items()]) / sum([v for _, v in allocatable.items()])
    logger.debug(f'{utilization=}')
    patch.status['utilization'] = round(utilization, digits)

def get_nodepool_allocatable_resource(nodes: kopf.Index, label_name: str, label_value: str, resource: str) -> dict(str, float):
    """
    Get allocatable resources by node.
    """
    allocatable = {}
    for node in nodes.get((label_name, label_value), []):
        allocatable.update({node['node_name']: float(quantity.parse_quantity(node['allocatable'][resource]))})
    return allocatable

def get_nodepool_resource_requests(nodes: kopf.Index, resource: str, logger: kopf.Logger) -> dict(str, float):
    """
    Get requested resource by node.
    """
    requests = {}
    for node_name, values in nodes.items():
        pods = []
        for value in values:
            for v in value:
                pods.append(v.get(resource, '0'))
        node_requests = float(sum([quantity.parse_quantity(pod) for pod in pods]))
        requests.update({node_name: node_requests})
    return requests

