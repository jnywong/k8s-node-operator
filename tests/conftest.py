import logging
import kopf
import pytest
import subprocess
from pathlib import Path
from k8s_node_operator.providers import create_provider

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
    # Assert npat crd is installed
    output = subprocess.check_output(
      ["kubectl", "get", "crds"]
    )
    assert "nodepoolallocationtargets.jupyter.org" in output.decode('utf-8')
    # Yield and delete when done
    try:
        yield
    finally:
        subprocess.run(
          ["kind", "delete", "cluster", "--name", "test-cluster"],
          check=True
        )

# Use no-op cloud provider for testing
# Note: kopfRunner instantiates provider within the handler, but we provider another instance as a fixture for test assertions
@pytest.fixture(scope='session', autouse=True)
def provider():
    provider = create_provider(name="TEST", npat_name="test-npat", spec=kopf.Spec, logger=logger)
    yield provider