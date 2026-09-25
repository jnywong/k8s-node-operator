import google.auth
import google.api_core
import kopf
import os
from dataclasses import dataclass
from enum import Enum
from google.cloud import container_v1
from kubernetes.aio import client, config
from kubernetes.aio.client.api_client import ApiClient
from typing import Protocol

class NodepoolState(Enum):
    READY = 1
    UPDATING = 2
    ERROR = 3


@dataclass
class Nodepool:
    state: NodepoolState
    name: str
    min_node_count: int
    max_node_count: int
    current_node_count: int
    target_min_node_count: int

class CloudProvider(Protocol):
    """
    Abstract class that allows structural subtyping/duck typing of all cloud providers (see https://typing.python.org/en/latest/reference/protocols.html).
    """
    def __init__(self, logger: kopf.Logger, npat_name: str | None = None):
        self.group = 'jupyter.org'
        self.version = 'v1'
        self.plural = 'nodepoolallocationtargets'
        self.name = npat_name or None
        if logger:
            self.log = logger
        else:
            print('No kopf logger detected.')

    async def get_nodepool(self):
        ... # Note that `...` is a Python placeholder object

    async def set_min_node_count(self, min_node_count: int, nodepool: Nodepool):
        ...

    async def get_k8s_current_node_count(self):
        """
        Get current node count with Kubernetes API. We use this as the source of truth for the number of nodes online, rather than cloud provider specific APIs.
        """
        await config.load_kube_config()
        async with ApiClient() as api:
            v1 = client.CoreV1Api(api)
            node_list = await v1.list_node()
        node_count = len(node_list.items)
        return node_count

    async def update_k8s_object_status(self, body: dict):
        await config.load_kube_config()
        async with ApiClient() as api:
            v1 = client.CustomObjectsApi(api)
            try:
                await v1.patch_cluster_custom_object(
                    group=self.group,
                    version=self.version,
                    plural=self.plural,
                    name=self.name,
                    body=body,
                    _content_type="application/merge-patch+json"
                )
                self.log.debug(f'{self.name} status patched.')
            except Exception as e:
                self.log.warning(f"{e}")
        
class GCPProvider(CloudProvider):
    """
    Methods for Google Cloud Platform (GCP).
    """
    def __init__(self, spec: kopf.Spec, npat_name: str, logger: kopf.Logger | None = None):
        super().__init__(logger=logger, npat_name = npat_name)
        self.project_name = spec.get("project") or os.environ.get("GCP_PROJECT_ID")
        self.cluster_name = spec.get("cluster") or os.environ.get("GCP_CLUSTER")
        self.zone = spec.get("zone") or os.environ.get("GCP_ZONE") # TODO: add support for regional clusters
        self.nodepool = spec.get("nodepool") or os.environ.get("GCP_NODEPOOL")
        self.prefix =  f"projects/{self.project_name}/zones/{self.zone}" if self.zone else f"projects/{self.project_name}/region/{self.region}"
        self.nodepool_name = self.prefix + f"/clusters/{self.cluster_name}/nodePools/{self.nodepool}"
        self.credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        self.credentials, self.project = google.auth.default()
        self.log.debug(self.credentials.get_cred_info())
        self.client = None

    async def __aenter__(self):
        self.client = container_v1.ClusterManagerAsyncClient(
            credentials=self.credentials
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.transport.close()

    async def _get_gcp_nodepool(self):
        request = container_v1.GetNodePoolRequest(
           name=self.nodepool_name
        )
        response = await self.client.get_node_pool(request=request)
        return response

    async def get_nodepool(self, target_min_node_count: int, gcp_nodepool: container_v1.NodePool | None = None):
        if not gcp_nodepool:
            gcp_nodepool = await self._get_gcp_nodepool()
        current_node_count = await self.get_k8s_current_node_count()
        nodepool = Nodepool(state=NodepoolState.UPDATING.name, name=self.nodepool, min_node_count=gcp_nodepool.autoscaling.min_node_count, max_node_count=gcp_nodepool.autoscaling.max_node_count, current_node_count=current_node_count,
        target_min_node_count=target_min_node_count)
        return nodepool

    async def wait_gcp_operation(self, operation_name: str):
        """
        Blocking call to wait until operation is completed.
        """
        name = '/'.join([self.prefix, "operations", operation_name])
        self.log.debug(f'Operation name: {name}')
        request = container_v1.GetOperationRequest(name=name)
        while True:
            response = await self.client.get_operation(request=request)
            if response.status != container_v1.Operation.Status.DONE:
                self.log.debug(f'Operation is {container_v1.Operation.Status(response.status).name}')
            # TODO: backoff on error
            else:
                return response

    async def set_min_node_count(self, target_min_node_count: int):
        gcp_nodepool = await self._get_gcp_nodepool()
        await self.update_k8s_object_status(
            body={
                "status": {
                    "nodepool_allocation": {
                        "state": NodepoolState.UPDATING.name,
                        "name": self.name,
                        "min_node_count": gcp_nodepool.autoscaling.min_node_count,
                        "max_node_count": gcp_nodepool.autoscaling.max_node_count,
                        "target_min_node_count": target_min_node_count
                    }
                }
            }
        )
        if target_min_node_count >= gcp_nodepool.autoscaling.max_node_count:
            self.log.warning(f'Target minimum node count {target_min_node_count} exceeds maximum node count.')
        elif target_min_node_count != gcp_nodepool.autoscaling.min_node_count:
            gcp_nodepool_autoscaling = container_v1.NodePoolAutoscaling(
                enabled = gcp_nodepool.autoscaling.enabled,
                min_node_count = target_min_node_count,
                max_node_count = gcp_nodepool.autoscaling.max_node_count,
                location_policy = gcp_nodepool.autoscaling.location_policy
            )
            request = container_v1.SetNodePoolAutoscalingRequest(
                name=self.nodepool_name,
                autoscaling=gcp_nodepool_autoscaling
            )
            try:
                operation = await self.client.set_node_pool_autoscaling(request=request)
            except google.api_core.exceptions.FailedPrecondition as e:
                # Kopf will retry the handler again
                raise kopf.TemporaryError(f"{e}")
            # Block until scaling operation is completed
            if operation:
                await self.wait_gcp_operation(operation_name = operation.name)
            # Update with new nodepool config
            gcp_nodepool = await self._get_gcp_nodepool()
            self.log.info(f'Minimum node count set to {gcp_nodepool.autoscaling.min_node_count}.')
        else:
            self.log.warning(f'Minimum node count is already set to {target_min_node_count}.')
        nodepool = await self.get_nodepool(gcp_nodepool=gcp_nodepool, target_min_node_count=target_min_node_count)
        return nodepool

class TestProvider(CloudProvider):
    """
    No-op cloud provider for testing and mocking.
    """
    def __init__(self, npat_name: str, logger: kopf.Logger):
        super().__init__(npat_name=npat_name, logger=logger)
        self._entered = False
        self._exited = False

    async def __aenter__(self):
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._exited = True

    async def get_nodepool(self, target_min_node_count: int):
        self.nodepool = Nodepool(
            name="test-pool",
            min_node_count=0, 
            max_node_count=0,
            current_node_count=0,
            target_min_node_count=target_min_node_count, # target_min_node_count is the only variable we are testing
        )
        return self.nodepool

    async def set_min_node_count(self, target_min_node_count: int):
        self.nodepool = Nodepool(
            name="test-nodepool",
            min_node_count=0,
            max_node_count=0,
            current_node_count=0,
            target_min_node_count=target_min_node_count, # target_min_node_count is the only variable we are testing
        )
        return self.nodepool


def create_provider(name: str, spec: kopf.Spec, npat_name: str, logger: kopf.Logger):
    if name == "GCP":
        return GCPProvider(spec=spec, npat_name = npat_name, logger=logger)
    elif name == "TEST":
        return TestProvider(npat_name = npat_name, logger=logger)