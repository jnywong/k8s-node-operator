import kopf
import pytest
from .conftest import logger
from k8s_autoscaler_plugins.operator import nodepool_allocation, delete_nodepool_allocation, k8s_nodes


class TestOperator:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("test_input, test_output", [([0, 'topology.kubernetes.io/zone=us-central1-b'], 'test-pool-1'), ([1, 'topology.kubernetes.io/zone=us-central1-c'], 'test-pool-2')])
    async def test_nodepool_allocation(self, fixture_node_index, test_input, test_output):
        """
        Test parametrized input returns parametrized output.
        """
        spec = {'nodepoolSelector': test_input[1], 'plugins': {'alwaysOn': {'minimum': test_input[0]}}}  # TODO: spec.plugins subject to change
        status = await nodepool_allocation(spec = spec, k8s_nodes = fixture_node_index, logger = logger)
        assert status['name'][0] == test_output

    @pytest.mark.asyncio
    @pytest.mark.parametrize("test_input, test_output", [([0, 'topology.kubernetes.io/zone=us-central1-b'], 'test-pool-1'), ([1, 'topology.kubernetes.io/zone=us-central1-c'], 'test-pool-2')])
    async def test_delete_nodepool_allocation(self, fixture_node_index, test_input, test_output):
        """
        Test parametrized input returns target minimum node count of 0.
        """

        spec = {'nodepoolSelector': test_input[1], 'plugins': {'alwaysOn': {'minimum': test_input[0]}}}  # TODO: spec.plugins subject to change
        patch = kopf.Status
        patch.status = {'nodepool_allocation': {}}
        nodepool = await delete_nodepool_allocation(spec=spec, patch=patch, k8s_nodes=fixture_node_index, logger=logger)
        assert nodepool.name == test_output
        assert int(nodepool.target_min_node_count) == 0

    def test_k8s_nodes(self, fixture_node):
        """
        Test in-memory index returns ready k8s nodes.
        """
        data = k8s_nodes(body=fixture_node, labels=fixture_node['metadata']['labels'], logger=logger)
        # TODO: generalize for other cloud providers
        assert data['cloud.google.com/gke-nodepool'] == 'test-pool-1'