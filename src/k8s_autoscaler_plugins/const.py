import os

PROVIDER_NAME = os.environ.get('K8S_NODE_OPERATOR_CLOUD_PROVIDER', '')
NODEPOOL_LABELS = {
    'GCP': 'cloud.google.com/gke-nodepool',
    'TEST': 'cloud.google.com/gke-nodepool'
}