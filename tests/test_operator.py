import kopf
import pytest
import subprocess
import time
from kopf.testing import KopfRunner
from unittest.mock import Mock
from .conftest import SRC_DIR, logger
from .utils import generate_test_npat_file
from k8s_node_operator.base import KubernetesClient
from k8s_node_operator.operator import nodepool_allocation, delete_nodepool_allocation



@pytest.mark.asyncio
class TestOperator:

    @pytest.mark.parametrize("test_input, test_output", [([0, 'topology.kubernetes.io/zone=us-central1-b'], 'test-pool-1'), ([1, 'topology.kubernetes.io/zone=us-central1-c'], 'test-pool-2')])
    async def test_nodepool_allocation(self, k8s_nodes, test_input, test_output):
        """
        Test parametrized input returns parametrized output.
        """
        spec = {'nodepoolSelector': test_input[1], 'plugins': {'alwaysOn': {'minimum': test_input[0]}}}  # TODO: spec.plugins subject to change
        status = await nodepool_allocation(spec = spec, k8s_nodes = k8s_nodes, logger = logger)
        assert status['name'][0] == test_output

    @pytest.mark.parametrize("test_input, test_output", [([0, 'topology.kubernetes.io/zone=us-central1-b'], 'test-pool-1'), ([1, 'topology.kubernetes.io/zone=us-central1-c'], 'test-pool-2')])
    async def test_delete_nodepool_allocation(self, k8s_nodes, test_input, test_output):
        """
        Test parametrized input returns target minimum node count of 0.
        """

        spec = {'nodepoolSelector': test_input[1], 'plugins': {'alwaysOn': {'minimum': test_input[0]}}}  # TODO: spec.plugins subject to change
        patch = kopf.Status
        patch.status = {'nodepool_allocation': {}}
        nodepool = await delete_nodepool_allocation(spec=spec, patch=patch, k8s_nodes=k8s_nodes, logger=logger)
        assert nodepool.name == test_output
        assert int(nodepool.target_min_node_count) == 0
