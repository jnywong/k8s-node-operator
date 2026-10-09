import kopf
import os
from enum import Enum
from google.cloud import container_v1
from kubernetes.aio import client, config
from kubernetes.aio.client.api_client import ApiClient
from k8s_node_operator.providers import CloudProvider

type NodepoolType = container_v1.NodePool | None  # TODO: update this when adding other cloud provider types.

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
    def __init__(self, name: str, zone: str, region: str):
        self.state: NodepoolState
        self.min_node_count: int
        self.max_node_count: int
        self.target_min_node_count: int
        self.name = name
        self.zone = zone
        self.region = region

    async def set_min_node_count(self):
        ...


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

def get_nodepool_list(node_list: list, region_label: str = 'topology.kubernetes.io/region', zone_label: str = 'topology.kubernetes.io/zone') -> list[Nodepool]:
    NODEPOOL_LABELS = {
        'GCP': 'cloud.google.com/gke-nodepool'
    }
    cloud_provider = os.environ.get('K8S_NODE_OPERATOR_CLOUD_PROVIDER', '')
    nodepool_name_label = NODEPOOL_LABELS[cloud_provider]
    nodepool_list = []
    for node in node_list:
        name = node.metadata.labels[nodepool_name_label]
        zone = node.metadata.labels[zone_label]
        region = node.metadata.labels[region_label]
        nodepool = Nodepool(name=name, zone=zone, region=region)
        nodepool_list.append(nodepool)
    unique_nodepools = list({nodepool.name: nodepool for nodepool in nodepool_list}.values())
    return unique_nodepools