import os
import pytest
import subprocess
import time
from kopf.testing import KopfRunner
from pathlib import Path
from .utils import generate_test_npat_file

# test_operator.py assumes that the npat CRD is already installed with kubectl apply -f helm/k8s_node_operator/nodepool_allocation_target.yaml. Make sure that no npat objects already exist in your k8s cluster prior to running the test suite.

# Path to kopf operator 
PROJECT_DIR = Path(__file__).parent.parent
SRC_DIR = PROJECT_DIR.joinpath('src/k8s_node_operator')

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