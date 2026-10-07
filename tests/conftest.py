import logging
import kopf
import pytest
import subprocess
from pathlib import Path
from k8s_autoscaler_plugins.providers import create_provider

logger = logging.getLogger(__name__)


PROJECT_DIR = Path(__file__).parent.parent
SRC_DIR = PROJECT_DIR.joinpath('src/k8s_autoscaler_plugins')
CRD_FILE = PROJECT_DIR.joinpath('helm/k8s_autoscaler_plugins/crds/nodepool_allocation_target.yaml')

@pytest.fixture(scope='session', autouse=True)
def create_kind_cluster():
    """
    A [kind cluster](https://kind.sigs.k8s.io/) for running a local Kubernetes cluster.
    
    Note: If the cluster is not destroyed properly, e.g. an error while developing the test suite, then this raises a 'CalledProcessError' the next time you run the tests. Manually destroy the cluster with `kind delete cluster --name test-cluster` before running the test suite again.
    """
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

@pytest.fixture(scope='session', autouse=True)
def provider():
    """
    Use no-op cloud provider for testing.
    
    Note: kopfRunner instantiates a provider within the handler routine, but we provide another instance as a fixture so that we can access its attributes for test assertions.
    """
    provider = create_provider(name="TEST", npat_name="test-npat", spec=kopf.Spec, logger=logger)
    yield provider