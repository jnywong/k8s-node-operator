import google.auth
import google.api_core
import kopf
import logging
import os
from abc import ABC
from google.cloud import container_v1
from types import TracebackType

class CloudProvider(ABC):
    """
    Abstract base class with Kubernetes API methods and standardizes the construction of all cloud providers (see https://peps.python.org/pep-3119/).
    """
    def __init__(self, logger: kopf.Logger | None = None, timeout: int = 300, interval: int = 10):
        if logger:
            self.log = logger
        else:
            self.log = logging.getLogger(__name__)

    async def __aenter__(self):
        ... # Note that `...` is a Python placeholder object

    async def __aexit__(self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None):
        ...

    async def get_nodepool(self, name: str, zone: str | None = None, region: str | None = None) -> dict:
        ...

    async def set_min_node_count(self, nodepool: Nodepool) -> None:
        ...
        
class GCPProvider(CloudProvider):
    """
    Methods for Google Cloud Platform (GCP).
    """
    def __init__(self, logger: kopf.Logger | None = None):
        super().__init__(logger=logger)
        self.project_name = os.environ.get('GCP_PROJECT_ID', '')
        self.cluster_name = os.environ.get('GCP_CLUSTER', '')
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

    def _get_prefix(self, zone: str | None = None, region: str | None = None):
        return f"projects/{self.project_name}/zones/{zone}" if zone else f"projects/{self.project_name}/region/{region}"

    def _get_request_name(self, name: str, zone: str | None = None, region: str | None = None):
        prefix = self._get_prefix(zone, region)
        request_name = '/'.join([prefix, f"clusters/{self.cluster_name}/nodePools/{name}"]) # TODO: use YARL
        return request_name

    async def _get_gcp_nodepool(self, name: str, zone: str | None = None, region: str | None = None) -> container_v1.NodePool:
        """
        Request a vendor-specific GCP nodepool.
        """
        request_name = self._get_request_name(name, zone, region)
        request = container_v1.GetNodePoolRequest(
           name=request_name
        )
        return await self.client.get_node_pool(request=request)

    async def get_nodepool(self, name: str, zone: str | None = None, region: str | None = None) -> dict:
        """
        Get non-vendor-specific nodepool config.
        """
        gcp_nodepool = await self._get_gcp_nodepool(name, zone, region)
        return {
            'name': name,
            'min_node_count': gcp_nodepool.autoscaling.min_node_count, 'max_node_count': gcp_nodepool.autoscaling.max_node_count
        } 
    
    async def wait_gcp_operation(self, operation_name: str, zone: str | None = None, region: str | None = None) -> container_v1.Operation:
        """
        Blocking call to wait until operation is completed.
        """
        name = '/'.join([self._get_prefix(zone, region), "operations", operation_name])
        request = container_v1.GetOperationRequest(name=name)
        while True:
            response = await self.client.get_operation(request=request)
            if response.status != container_v1.Operation.Status.DONE:
                self.log.debug(f'Operation is {container_v1.Operation.Status(response.status).name}')
            # TODO: backoff on error
            else:
                return response

    async def set_min_node_count(self, nodepool: Nodepool) -> None:
        """
        Set the autoscaling minimum node count of a GCP nodepool.
        """
        target_min_node_count = nodepool.target_min_node_count
        gcp_nodepool = await self._get_gcp_nodepool(name=nodepool.name, zone=nodepool.zone, region=nodepool.region)
        # Decide whether to scale
        if target_min_node_count >= gcp_nodepool.autoscaling.max_node_count:
            self.log.info(f'Target minimum node count {target_min_node_count} exceeds maximum node count.')
        elif target_min_node_count != gcp_nodepool.autoscaling.min_node_count:
            gcp_nodepool_autoscaling = container_v1.NodePoolAutoscaling(
                enabled = gcp_nodepool.autoscaling.enabled,
                min_node_count = target_min_node_count,
                max_node_count = gcp_nodepool.autoscaling.max_node_count,
                location_policy = gcp_nodepool.autoscaling.location_policy
            )
            request_name = self._get_request_name(nodepool.name, nodepool.zone, nodepool.region)
            request = container_v1.SetNodePoolAutoscalingRequest(
                name=request_name,
                autoscaling=gcp_nodepool_autoscaling
            )
            try:
                operation = await self.client.set_node_pool_autoscaling(request=request)
                self.log.debug(f'{operation.name=}')
            except google.api_core.exceptions.FailedPrecondition as e:
                # This can happen e.g. if nodepool state is already busy running another operation. Kopf will retry the handler again on TemporaryError
                raise kopf.TemporaryError(f"{e}")

class TestProvider(CloudProvider):
    """
    No-op cloud provider for testing and mocking.
    """
    def __init__(self, logger: kopf.Logger | None = None):
        super().__init__(logger=logger)
        self._entered = False
        self._exited = False

    async def __aenter__(self):
        self._entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._exited = True

    async def get_nodepool(self, name: str, zone: str | None = None, region: str | None = None) -> dict:
        return {
            'name': 'test-pool',
            'min_node_count': 0,
            'max_node_count': 1
        } 

    async def set_min_node_count(self, nodepool: Nodepool) -> None:
        ...


def create_provider(name: str, logger: kopf.Logger | None = None) -> CloudProvider:
    if name == "GCP":
        return GCPProvider(logger = logger)
    elif name == "TEST":
        return TestProvider(logger = logger)
    else:
        raise ValueError(f"Provider name '{name}' not recognized.")
