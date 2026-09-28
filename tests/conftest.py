import logging
import pytest
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


PROJECT_DIR = Path(__file__).parent.parent
SRC_DIR = PROJECT_DIR.joinpath('src/k8s_node_operator')
CRD_FILE = PROJECT_DIR.joinpath('helm/k8s_node_operator/crds/nodepool_allocation_target.yaml')

@pytest.fixture(scope='session', autouse=True)
def create_kind_cluster():
    subprocess.run(
        ["kind", "create", "cluster", "--name", "test-cluster"],
        check=True
    )
    # Install npat crd
    subprocess.run(
        ["kubectl", "apply", "-f", CRD_FILE],
        check=True
    )
    check_crd()
    try:
        yield
    finally:
        subprocess.run(
          ["kind", "delete", "cluster", "--name", "test-cluster"],
          check=True
        )

def check_crd():
    output = subprocess.check_output(
      ["kubectl", "get", "crds"]
    )
    assert "nodepoolallocationtargets.jupyter.org" in output.decode('utf-8')