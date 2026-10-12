import kopf
import os
from enum import Enum
from google.cloud import container_v1
from kubernetes.aio import client, config
from kubernetes.aio.client.api_client import ApiClient

type NodepoolType = container_v1.NodePool | None  # TODO: update this when adding other cloud provider types.

NODEPOOL_LABELS = {
    'GCP': 'cloud.google.com/gke-nodepool'
}

class NodepoolState(Enum):
    """
    An enumerated list of nodepool states.
    """
    READY = 1
    UPDATING = 2
    ERROR = 3


class Nodepool:
    """
    Abstract the concept of a nodepool independently of cloud-specific vendors.
    """
    def __init__(self, name: str, zone: str, region: str, min_node_count: int, max_node_count: int, target_min_node_count: int, state: str):
        self.name = name
        self.zone = zone
        self.region = region
        self.min_node_count = min_node_count
        self.max_node_count = max_node_count
        self.target_min_node_count = target_min_node_count
        self.state = state
class KubernetesClient:
    async def __aenter__(self):
        await self.load_kubernetes_config()
        self.api_client = ApiClient()
        self.api_core = client.CoreV1Api(self.api_client)
        self.api_custom_objects = client.CustomObjectsApi(self.api_client)
        return self

    async def __aexit__(self,  exc_type, exc, tb):
            await self.api_client.close()
    
    async def load_kubernetes_config(self) -> None:
        """
        Tries to authenticate to Kubernetes API from within a pod at first for production environments, otherwise it loads your local Kubernetes config context from `~/.kube/config` for local development environments.
        """
        try:
            config.load_incluster_config()
        except config.ConfigException:
            await config.load_kube_config()

    async def list_nodes(self, label_selector: str = '', index_nodes: kopf.Index | None = None) -> list[client.V1Node]:
        """
        List k8s nodes using in-memory kopf.Index if it exists, otherwise makes k8s API call.
        """

        if not index_nodes:
            try:
                node_list = await self.api_core.list_node()
                return node_list.items
            except Exception as e:
                raise e

def get_nodepool_list(node_list: list, provider_name: str | None = None, region_label: str = 'topology.kubernetes.io/region', zone_label: str = 'topology.kubernetes.io/zone') -> list[dict]:

    if not provider_name:
        provider_name = os.environ.get('K8S_NODE_OPERATOR_CLOUD_PROVIDER', '')
    nodepool_name_label = NODEPOOL_LABELS[provider_name]
    nodepool_list = []
    for node in node_list:
        item = {
            'name': node.metadata.labels[nodepool_name_label],
            'zone': node.metadata.labels[zone_label],
            'region': node.metadata.labels[region_label]
        }
        if item not in nodepool_list:
            nodepool_list.append(item)
    return nodepool_list