import kopf
import pytest
from .conftest import logger
from k8s_autoscaler_plugins.base import NodepoolState
from k8s_autoscaler_plugins.operator import nodepool_allocation, delete_nodepool_allocation, k8s_nodes, reconcile_kubernetes
from k8s_autoscaler_plugins.const import RETRY_LIMIT


class TestOperator:

    npat_name = 'test-npat'

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
    @pytest.mark.parametrize("test_input, test_output", [
        ({'target_min_node_count': 0, 'nodepoolSelector': 'topology.kubernetes.io/zone=us-central1-b'}, {'name': 'test-pool-1'}), ({'target_min_node_count': 1, 'nodepoolSelector': 'topology.kubernetes.io/zone=us-central1-c'}, {'name': 'test-pool-2'})])
    async def test_delete_nodepool_allocation(self, fixture_node_index, test_input, test_output):
        """
        Test parametrized input returns target minimum node count of 0.
        """

        spec = {'nodepoolSelector': test_input['nodepoolSelector'], 'plugins': {'alwaysOn': {'minimum': test_input['target_min_node_count']}}}  # TODO: spec.splugins subject to change
        kopf_patch = kopf.Status
        kopf_patch.status = {'nodepool_allocation': {}}
        status = await delete_nodepool_allocation(spec=spec, patch=kopf_patch, k8s_nodes=fixture_node_index, logger=logger)
        logger.warning(f'{status=}')
        assert status.get('name', '') == [test_output['name']]
        assert status.get('target_min_node_count', '') == [0]

    def test_k8s_nodes(self, fixture_node):
        """
        Test in-memory index returns ready k8s nodes.
        """
        data = k8s_nodes(body=fixture_node, labels=fixture_node['metadata']['labels'], logger=logger)
        # TODO: generalize for other cloud providers
        assert data['cloud.google.com/gke-nodepool'] == 'test-pool-1'

    @pytest.mark.asyncio
    @pytest.mark.parametrize("test_input, test_output", [({'current_node_count': 1, 'target_min_node_count': 1, 'nodepoolSelector': 'topology.kubernetes.io/zone=us-central1-b', 'name': 'test-pool-1'}, {'status': NodepoolState.READY.name, 'raises': False, 'timeout': False}), ({'current_node_count': 0, 'target_min_node_count': 1, 'nodepoolSelector': 'topology.kubernetes.io/zone=us-central1-c', 'name': 'test-pool-2'}, {'status': NodepoolState.UPDATING.name, 'raises': True, 'timeout': False}),
    ({'current_node_count': 0, 'target_min_node_count': 1, 'nodepoolSelector': 'topology.kubernetes.io/zone=us-central1-c', 'name': 'test-pool-2'}, {'status': NodepoolState.ERROR.name, 'raises': True, 'timeout': True})])
    async def test_reconcile_kubernetes(self, fixture_node_index, test_input, test_output, mocker):
        """
        Test reconciliation between target state and current Kubernetes state.

        Parameter tests:
          1. Reconciliation succeeds
          2. Reconciliation is below RETRY_LIMIT and raises kopf.TemporaryError 
          3. Reconciliation is above RETRY_LIMIT and raises kopf.PermanentError
        """
        # Set cloud provider values (we're not testing for these values here).
        min_node_count = 1
        max_node_count = 2
        # Set kopf handler inputs
        spec = {'nodepoolSelector': test_input['nodepoolSelector'], 'plugins': {'alwaysOn': {'minimum': test_input['target_min_node_count']}}}
        status = {'nodepool_allocation': {'name': [test_input['name']], 'status': [NodepoolState.UPDATING.name], 'min_node_count': [min_node_count], 'max_node_count': [max_node_count], 'current_node_count': [test_input['current_node_count']], 'target_min_node_count': [test_input['target_min_node_count']]}}
        patch = kopf.Patch
        patch.status = status
        # Mock API calls to cloud provider
        mock_get_nodepool = mocker.patch('k8s_autoscaler_plugins.providers.TestProvider.get_nodepool')
        mock_get_nodepool.return_value = {
            'name': 'test-pool-1',
            'min_node_count': min_node_count,
            'max_node_count': max_node_count
        }
        mock_get_current_node_count = mocker.patch('k8s_autoscaler_plugins.base.Nodepool.get_current_node_count')
        mock_get_current_node_count.return_value = test_input['current_node_count']
        retry = 0
        while retry < RETRY_LIMIT:
            logger.info(f'{retry=}')
            if test_output['raises']:
                with pytest.raises(kopf.TemporaryError):
                    await reconcile_kubernetes(spec=spec, status=status, name = self.npat_name, k8s_nodes=fixture_node_index, patch=patch, logger=logger, retry=retry)
                    assert status['nodepool_allocation']['status'] == test_output['status']
            else:
                await reconcile_kubernetes(spec=spec, status=status, name = self.npat_name, k8s_nodes=fixture_node_index, patch=patch, logger=logger, retry=retry)
                assert status['nodepool_allocation']['name'] == [test_input['name']]
                assert status['nodepool_allocation']['status'] == test_output['status']
            retry += 1
        if test_output['timeout']:
            logger.info(f'{retry=}')
            with pytest.raises(kopf.PermanentError):
                await reconcile_kubernetes(spec=spec, status=status, name = self.npat_name, k8s_nodes=fixture_node_index, patch=patch, logger=logger, retry=retry)
            assert status['nodepool_allocation']['status'] == test_output['status']
