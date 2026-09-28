import os
import pytest
import subprocess
import time
from kopf.testing import KopfRunner
from .conftest import SRC_DIR
from .utils import generate_test_npat_file

# Use no-op cloud provider for testing
os.environ["K8S_NODE_OPERATOR_CLOUD_PROVIDER"] = "TEST"

@pytest.mark.parametrize("target_min_node_count", [0, 1])
def test_npat_create_and_delete(target_min_node_count):
    npat_file = generate_test_npat_file(name='test-npat', target_min_node_count=target_min_node_count)
    with KopfRunner(['run', '-A', '--verbose', SRC_DIR.joinpath('operator.py').as_posix()]) as runner:
        subprocess.run('kubectl apply -f' + npat_file, shell=True, check=True)
        time.sleep(1)
        subprocess.run('kubectl delete -f' + npat_file, shell=True, check=True)
        time.sleep(1)

    assert runner.exit_code == 0
    assert runner.exception is None
    assert "NodepoolAllocationTarget" in runner.output
    assert "'spec': {'minimumNodeCount': " + f"'{target_min_node_count}'" + "}" in runner.output
    assert 'Deleted, really deleted' in runner.output

def test_npat_create_update_and_delete():
    npat_file = generate_test_npat_file(name='test-npat', target_min_node_count=0)
    with KopfRunner(['run', '-A', '--verbose', SRC_DIR.joinpath('operator.py').as_posix()]) as runner:
        subprocess.run('kubectl apply -f' + npat_file, shell=True, check=True)
        time.sleep(1)
        subprocess.run('kubectl patch npat test-npat --type merge -p \'{\"spec\": {\"minimumNodeCount\": \"1\"}}\'', shell=True, check=True)
        time.sleep(1)
        subprocess.run('kubectl delete -f' + npat_file, shell=True, check=True)
        time.sleep(1)

    assert runner.exit_code == 0
    assert runner.exception is None
    assert "NodepoolAllocationTarget" in runner.output
    assert "'spec': {'minimumNodeCount': '0'}" in runner.output
    assert "'spec': {'minimumNodeCount': '1'}" in runner.output
    assert 'Deleted, really deleted' in runner.output


# TODO:
# - when current node count < target => timeout and that timeout and status is respected
# - label selector is passed through
# - k8s object status is updated where expected