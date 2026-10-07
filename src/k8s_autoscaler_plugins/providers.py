import asyncio
import google.auth
import google.api_core
import kopf
import logging
import os
from abc import ABC
from dataclasses import dataclass
from google.cloud import container_v1
from kubernetes.aio import client, config
from kubernetes.aio.client.api_client import ApiClient
from types import TracebackType
from src.k8s_autoscaler_plugins.base import NodepoolState


@dataclass
class Nodepool:
    """
    A dataclass to abstract the concept of a nodepool independently of cloud-specific vendors.
    """
    state: str
    name: str
    min_node_count: int
    max_node_count: int
    target_min_node_count: int

type NodepoolType = container_v1.NodePool | None  # TODO: update this when adding other cloud provider types.

class CloudProvider(ABC):
    """
    Abstract base class with Kubernetes API methods and standardizes the construction of all cloud providers (see https://peps.python.org/pep-3119/).
    """
    def __init__(self, logger: kopf.Logger | logging.Logger | None = None, npat_name: str | None = None, timeout: int = 300, interval: int = 10):
        self.group = 'jupyter.org'
        self.version = 'v1'
        self.plural = 'nodepoolallocationtargets'
        self.name = npat_name or None
        self.timeout = timeout
        self.interval = interval
        if logger:
            self.log = logger
        else:
            print('No kopf logger detected.')

    async def __aenter__(self):
        ... # Note that `...` is a Python placeholder object

    async def __aexit__(self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None):
        ...

    async def get_nodepool(self, state: str, target_min_node_count: int):
        ...

    async def set_min_node_count(self, min_node_count: int):
        ...

    async def load_kubernetes_config(self) -> None:
        """
        Tries to authenticate to Kubernetes API from within a pod at first for production environments, otherwise it loads your local Kubernetes config context from `~/.kube/config` for local development environments.
        """
        try:
            config.load_incluster_config()
        except config.ConfigException:
            await config.load_kube_config()


    async def get_k8s_object_status(self) -> dict:
        """
        Get an object's status of a Kubernetes custom resource.
        """
        await self.load_kubernetes_config()
        async with ApiClient() as api:
            v1 = client.CustomObjectsApi(api)
            try:
                obj = await v1.get_cluster_custom_object(
                    group=self.group,
                    version=self.version,
                    plural=self.plural,
                    name=self.name
                )
                return obj["status"]
            except Exception as e:
                self.log.warning(f"{e}")
                raise

    async def update_k8s_object_status(self, body: dict) -> None:
        """
        Patch an object status of a Kubernetes custom resource.
        """
        await self.load_kubernetes_config()
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
                raise
        
class GCPProvider(CloudProvider):
    """
    Methods for Google Cloud Platform (GCP).
    """
    def __init__(self, spec: kopf.Spec, npat_name: str, logger: kopf.Logger | None = None):
        super().__init__(logger=logger, npat_name = npat_name)
        self.project_name = spec.get("project") or os.environ.get("GCP_PROJECT_ID")
        self.cluster_name = spec.get("cluster") or os.environ.get("GCP_CLUSTER")
        self.zone = spec.get("zone") or os.environ.get("GCP_ZONE")
        self.region = spec.get("region") or os.environ.get("GCP_REGION") # TODO: add support for regional clusters
        self.nodepool = spec.get("nodepoolName", "") or os.environ.get("GCP_NODEPOOL", "")
        self.nodepool_label_name = spec.get("nodepoolLabelName", "") or os.environ.get("GCP_NODEPOOL_NAME", "")
        self.nodepool_label_value = spec.get("nodepoolLabelValue", "") or os.environ.get("GCP_NODEPOOL_LABEL", "")  # NOTE: repetition -- can nodepool label != self.nodepool name?
        self.prefix =  f"projects/{self.project_name}/zones/{self.zone}" if self.zone else f"projects/{self.project_name}/region/{self.region}"
        self.nodepool_name = self.prefix + f"/clusters/{self.cluster_name}/nodePools/{self.nodepool}"
        self.credentials_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        self.credentials, self.project = google.auth.default()
        self.log.debug(self.credentials.get_cred_info())

    async def __aenter__(self):
        self.client = container_v1.ClusterManagerAsyncClient(
            credentials=self.credentials
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.client.transport.close()

    async def _get_gcp_nodepool(self) -> container_v1.NodePool:
        """
        Request a vendor-specific GCP nodepool.
        """
        request = container_v1.GetNodePoolRequest(
           name=self.nodepool_name
        )
        response = await self.client.get_node_pool(request=request)
        return response

    async def get_nodepool(self, state: str, target_min_node_count: int, gcp_nodepool: NodepoolType = None):
        """
        Get a non-vendor-specific nodepool.
        """
        if not gcp_nodepool:
            gcp_nodepool = await self._get_gcp_nodepool()
        nodepool = Nodepool(state=state, name=self.nodepool, min_node_count=gcp_nodepool.autoscaling.min_node_count, max_node_count=gcp_nodepool.autoscaling.max_node_count,
        target_min_node_count=target_min_node_count)
        return nodepool

    async def wait_gcp_operation(self, operation_name: str) -> container_v1.Operation:
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

    async def set_min_node_count(self, target_min_node_count: int) -> Nodepool:
        """
        Set the minimum node count of a GCP nodepool.
        """
        # Update npat with current nodepool state
        gcp_nodepool = await self._get_gcp_nodepool() # We deal with the GCP-specific nodepool object here since we will pass that into the GCP request later
        # Decide whether to scale
        if target_min_node_count >= gcp_nodepool.autoscaling.max_node_count:
            self.log.info(f'Target minimum node count {target_min_node_count} exceeds maximum node count.')  # TODO: is there a way to notify end-user of incompatible spec?
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
                self.log.debug(f'{operation.name=}')
            except google.api_core.exceptions.FailedPrecondition as e:
                # This can happen e.g. if nodepool state is already busy running another operation.
                await self.update_k8s_object_status(
                    body={
                        "status": {
                            "state": NodepoolState.ERROR.name,
                            "nodepool_allocation": {
                                "name": self.nodepool,
                                "min_node_count": gcp_nodepool.autoscaling.min_node_count,
                                "max_node_count": gcp_nodepool.autoscaling.max_node_count,
                                "target_min_node_count": target_min_node_count
                            }
                        }
                    }
                )
                # Kopf will retry the handler again on TemporaryError
                raise kopf.TemporaryError(f"{e}")
            # Block until current scaling operation is completed
            if operation:
                await self.wait_gcp_operation(operation_name = operation.name)
            # Update with new nodepool state
            gcp_nodepool = await self._get_gcp_nodepool()
            self.log.info(f'Minimum node count successfully set to {gcp_nodepool.autoscaling.min_node_count}.')
        else:
            self.log.info(f'Minimum node count is already set to {target_min_node_count}.')  # TODO: again, can we notify end-user here? Emit event?
        nodepool = await self.get_nodepool(state = NodepoolState.READY.name, gcp_nodepool=gcp_nodepool, target_min_node_count=target_min_node_count)
        return nodepool

class TestProvider(CloudProvider):
    """
    No-op cloud provider for testing and mocking.
    """
    def __init__(self, npat_name: str, logger: kopf.Logger | None = None):
        super().__init__(npat_name=npat_name, logger=logger)
        self._entered = False
        self._exited = False

    async def __aenter__(self):
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._exited = True

    async def get_nodepool(self, state: str, target_min_node_count: int, nodepool = None) -> Nodepool:
        self.nodepool = Nodepool(
            name="test-pool",
            state=NodepoolState.READY.name,
            min_node_count=0, 
            max_node_count=0,
            target_min_node_count=target_min_node_count, # target_min_node_count is the only variable we are testing
        )
        return self.nodepool

    async def set_min_node_count(self, target_min_node_count: int) -> Nodepool:
        self.nodepool = Nodepool(
            name="test-nodepool",
            state=NodepoolState.READY.name,
            min_node_count=0,
            max_node_count=0,
            target_min_node_count=target_min_node_count, # target_min_node_count is the only variable we are testing
        )
        return self.nodepool


def create_provider(name: str,  npat_name: str, spec: kopf.Spec, logger: kopf.Logger | logging.Logger | None = None) -> CloudProvider:
    if name == "GCP":
        return GCPProvider(spec=spec, npat_name = npat_name, logger=logger)
    elif name == "TEST":
        return TestProvider(npat_name = npat_name, logger=logger)
    else:
        raise ValueError(f"Provider name '{name}' not recognized.")
