import kopf
import os
from enum import Enum
from google.cloud import container_v1
from kubernetes.aio import client, config
from kubernetes.aio.client.api_client import ApiClient
from k8s_node_operator.providers import create_provider


type NodepoolType = container_v1.NodePool | None  # TODO: update this when adding other cloud provider types.

PROVIDER_NAME = os.environ.get('K8S_NODE_OPERATOR_CLOUD_PROVIDER', '')
NODEPOOL_LABELS = {
    'GCP': 'cloud.google.com/gke-nodepool'
}

class Node:
    """
    Abstract the concept of a node independently of cloud-specific vendors.
    """
    name_label = 'kubernetes.io/hostname'
    region_label = 'topology.kubernetes.io/region'
    zone_label = 'topology.kubernetes.io/zone'
    nodepool_label = NODEPOOL_LABELS[PROVIDER_NAME]

    def __init__(self, node_name: str, region: str, zone: str, label_selector: str, nodepool_name: str):
        self.node_name = node_name
        self.region = region
        self.zone = zone
        self.label_selector = label_selector
        self.nodepool_name = nodepool_name

    @classmethod
    async def list_node(cls, label_selector: str = '', index: kopf.Index | None = None) -> list[Node]:
        """
        List nodes by label selector from in-memory kopf index if it exists, otherwise make a Kubernetes API call.
        """
        if index:
            return cls.from_index(index=index, label_selector=label_selector)
        else:
            return await cls.from_k8s_api(label_selector=label_selector)

    @classmethod
    async def from_k8s_api(cls, label_selector: str = '') -> list[client.V1Node]:
        """
        Get a list of Node objects from Kubernetes API call.
        """
        async with KubernetesClient() as client:
            try:
                node_list = await client.api_core.list_node(label_selector=label_selector)
            except Exception as e:
                raise kopf.TemporaryError(f'{e}')
        return [cls.from_k8s_node(node, label_selector) for node in node_list.items]

    @classmethod
    def from_k8s_node(cls, node: client.V1Node, label_selector:str = '') -> Node:
        """
        Construct a Node object from a client.V1Node element of the from_k8s_api() method.
        """
        return cls(node_name=node.metadata.labels[cls.name_label], region=node.metadata.labels[cls.region_label], zone=node.metadata.labels[cls.zone_label], label_selector=label_selector, nodepool_name=node.metadata.labels[cls.nodepool_label])

    @classmethod
    def from_index(cls, index: kopf.Index,  label_selector: str = '') -> list[Node]:
        """
        Construct a list of Node objects from the kopf in-memory index of Kubernetes nodes.
        """
        # Convert dict of list to list of dict
        node_list = [dict(zip(index, v)) for v in zip(*index.values())] 
        return [cls.from_dict(node, label_selector) for node in node_list]

    @classmethod
    def from_dict(cls, node: dict,  label_selector: str = '') -> Node:
        """
        Construct a Node object from a node_list element of the from_index() method.
        """
        if label_selector:
            label_selector_split = label_selector.split('=')
            label_selector_name = label_selector_split[0]
            label_selector_value = label_selector_split[1]
            if node[label_selector_name] == label_selector_value:
                return cls(node_name=node[cls.name_label], region=node[cls.region_label], zone=node[cls.zone_label], label_selector=label_selector, nodepool_name=node[cls.nodepool_label])
            else:
                pass
        else:
            return cls(node_name=node[cls.name_label], region=node[cls.region_label], zone=node[cls.zone_label], label_selector=label_selector, nodepool_name=node[cls.nodepool_label])

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
    def __init__(self, name: str, zone: str, region: str, label_selector: str):
        self.name = name
        self.zone = zone
        self.region = region
        self.label_selector = label_selector
        self.min_node_count = None
        self.max_node_count = None
        self.target_min_node_count = None
        self.current_node_count = None
        self.state = None
        self.status = {
            'name': self.name, 
            'state': self.state, 
            'min_node_count': self.min_node_count,
            'max_node_count': self.max_node_count,
            'target_min_node_count': self.target_min_node_count,
            'current_node_count': self.current_node_count
        }

    @classmethod
    async def list_nodepool(cls, node_list: list[Node], label_selector: str = '') -> list[Nodepool]:
        """
        List nodepools from a node list.
        """
        nodepool_list = [Nodepool.from_node(node) for node in node_list]
        # Get list of unique nodepools
        unique_nodepool_names = list(set([nodepool.name for nodepool in nodepool_list]))
        unique_nodepool_list = []
        for u in unique_nodepool_names:
            for nodepool in nodepool_list:
                if u == nodepool.name:
                    unique_nodepool_list.append(nodepool)
                    break
        # Get nodepool config from cloud provider
        async with create_provider(PROVIDER_NAME) as provider:
            for nodepool in unique_nodepool_list:
                data = await provider.get_nodepool(name=nodepool.name, zone = nodepool.zone, region = nodepool.region)
                nodepool.min_node_count = data['min_node_count']
                nodepool.max_node_count = data['max_node_count']
                nodepool.current_node_count = nodepool.get_current_node_count(node_list)
                nodepool.state = NodepoolState.READY.name
                nodepool.status = nodepool.get_status(nodepool)
        return unique_nodepool_list

    @classmethod
    def from_node(cls, node: Node) -> Nodepool:
        """
        Construct Nodepool object from Node object.
        """
        return cls(name=node.nodepool_name, zone=node.zone, region=node.region, label_selector=node.label_selector)

    def get_current_node_count(self, node_list: list[Node]) -> int:
        """
        Get current node count from node list.
        """
        node_count = 0
        for node in node_list:
            if node.nodepool_name == self.name:
                node_count += 1
        return node_count

    async def set_min_node_count(self, target_min_node_count: int):
        """
        Set nodepool minimum node count with cloud provider.
        """
        self.target_min_node_count = target_min_node_count
        self.state = NodepoolState.UPDATING.name
        async with create_provider(PROVIDER_NAME) as provider:
            await provider.set_min_node_count(self)

    def get_status(self, nodepool: Nodepool) -> dict:
        """
        Get nodepool status as a dictionary.
        """
        self.status = {
            'name': self.name, 
            'state': self.state, 
            'min_node_count': self.min_node_count,
            'max_node_count': self.max_node_count,
            'target_min_node_count': self.target_min_node_count,
            'current_node_count': self.current_node_count
        }
        return self.status
    
    @staticmethod
    def get_status_list(nodepool_list: list[Nodepool]) -> dict:
        """
        Get overall state of nodepool list, with a list of values for each status key.
        """
        # Get overall state
        state = [nodepool.status['state'] for nodepool in nodepool_list]
        if NodepoolState.ERROR.name in state:
            state = NodepoolState.ERROR.name
        elif NodepoolState.UPDATING.name in state:
            state = NodepoolState.UPDATING.name
        else:
            state = NodepoolState.READY.name
        # Get list for each status key
        status = dict.fromkeys(iter(nodepool_list[0].status), [])
        for k, v in status.items():
            values = []
            for nodepool in nodepool_list:
                values.append(getattr(nodepool, k))
            status[k] = values
        status.update({'status': state})
        return status

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
