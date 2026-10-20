import pytest
import subprocess
import time
from kopf.testing import KopfRunner
from .conftest import SRC_DIR, logger
from .utils import generate_test_npat_file
from k8s_node_operator.base import KubernetesClient


@pytest.mark.asyncio
class TestOperator:

    npat_name = 'test-npat'

    @pytest.mark.parametrize("target_min_node_count", [0, 1])
    async def test_npat_create_and_delete(self, provider, target_min_node_count):
        """
        Create and delete npat. Assert intermediate npat object status' match parametrized target_min_node_count.
        """
        npat_file = generate_test_npat_file(name=self.npat_name, target_min_node_count=target_min_node_count)
        with KopfRunner(['run', '-A', '--verbose', SRC_DIR.joinpath('operator.py').as_posix()]) as runner:
            # Create
            subprocess.run('kubectl apply -f' + npat_file, shell=True, check=True)
            time.sleep(1)
            async with KubernetesClient() as client:
                status = await client.get_custom_resource_object(self.npat_name)
            assert int(status['nodepool_allocation']['target_min_node_count'][0]) == target_min_node_count
            # Delete
            subprocess.run('kubectl delete -f ' + npat_file,
                shell=True,
                check=True
            )
            time.sleep(1)
            with pytest.raises(Exception):
                async with KubernetesClient() as client:
                    status = await client.get_custom_resource_object(self.npat_name)
        assert runner.exit_code == 0
        assert runner.exception is None
        assert "NodepoolAllocationTarget" in runner.output
        assert "'spec': {'minimumNodeCount': " + f"'{target_min_node_count}'" + "}" in runner.output
        assert 'Deleted, really deleted' in runner.output

    async def test_npat_create_update_and_delete(self, provider):
        """
        Create, update and delete npat. Assert intermediate npat object status' match target_min_node_count.
        """
        create_target_min_node_count = 0
        npat_file = generate_test_npat_file(name=self.npat_name, target_min_node_count=create_target_min_node_count)
        with KopfRunner(['run', '-A', '--verbose', SRC_DIR.joinpath('operator.py').as_posix()]) as runner:
            # Create
            subprocess.run('kubectl apply -f' + npat_file, shell=True, check=True)
            time.sleep(1)
            async with KubernetesClient() as client:
                status = await client.get_custom_resource_object(self.npat_name)
            assert int(status['nodepool_allocation']['target_min_node_count'][0]) == create_target_min_node_count
            # Update
            update_target_min_node_count = 0
            subprocess.run('kubectl patch npat ' + self.npat_name + ' --type merge -p \'{\"spec\": {\"minimumNodeCount\": \"' + str(update_target_min_node_count) + '\"}}\'', shell=True, check=True)
            time.sleep(1)
            async with KubernetesClient() as client:
                status = await client.get_custom_resource_object(self.npat_name)
            logger.warning(f'{status=}')
            assert int(status['nodepool_allocation']['target_min_node_count'][0]) == update_target_min_node_count
            # Delete
            subprocess.run('kubectl delete -f' + npat_file, shell=True, check=True)
            time.sleep(1)
            with pytest.raises(Exception):
                async with KubernetesClient() as client:
                    status = await client.get_custom_resource_object(self.npat_name)

        assert runner.exit_code == 0
        assert runner.exception is None
        assert "NodepoolAllocationTarget" in runner.output
        assert 'Deleted, really deleted' in runner.output

# TODO
# - use kopf.OperatorRegistry to isolate handlers for testing 