import os
import pytest
import subprocess
import time
from kopf.testing import KopfRunner
from .conftest import SRC_DIR, logger
from .utils import generate_test_npat_file

os.environ["K8S_NODE_OPERATOR_CLOUD_PROVIDER"] = "TEST"

@pytest.mark.asyncio
class TestOperator:
    @pytest.fixture(autouse=True)
    def setup(self, provider):
        self.npat_name = 'test-npat'
        provider.name = self.npat_name

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
            status = await provider.get_k8s_object_status()
            assert int(status['nodepool_allocation']['target_min_node_count']) == target_min_node_count
            # Delete
            subprocess.run('kubectl delete -f ' + npat_file,
                shell=True,
                check=True
            )
            time.sleep(1)
            with pytest.raises(Exception):
                status = await provider.get_k8s_object_status()
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
            status = await provider.get_k8s_object_status()
            assert int(status['nodepool_allocation']['target_min_node_count']) == create_target_min_node_count
            # Update
            update_target_min_node_count = 0
            subprocess.run('kubectl patch npat ' + self.npat_name + ' --type merge -p \'{\"spec\": {\"minimumNodeCount\": \"' + str(update_target_min_node_count) + '\"}}\'', shell=True, check=True)
            time.sleep(1)
            status = await provider.get_k8s_object_status()
            logger.warning(f'{status=}')
            assert int(status['nodepool_allocation']['target_min_node_count']) == update_target_min_node_count
            # Delete
            subprocess.run('kubectl delete -f' + npat_file, shell=True, check=True)
            time.sleep(1)
            with pytest.raises(Exception):
                status = await provider.get_k8s_object_status()

        assert runner.exit_code == 0
        assert runner.exception is None
        assert "NodepoolAllocationTarget" in runner.output
        assert 'Deleted, really deleted' in runner.output
