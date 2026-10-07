import kopf
from typing import Any, Dict
from src.k8s_autoscaler_plugins.base import NodepoolState

# Nodepool utilization threshold (nput) custom resource

@kopf.on.create('nodepoolutilizationthreshold')
@kopf.on.update('nodepoolutilizationthreshold')
async def nodepool_utilization(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> Dict:
    """
    Get current utilization on create or update.
    """
    patch.status['utilization'] = 0.7
    patch.status['state'] = NodepoolState.READY.name


# @kopf.on.delete('nodepoolutilizationthreshold')
# async def delete_nodepool_utilization(spec: kopf.Spec, patch: kopf.Patch, name: str, logger: kopf.Logger, **_: Any) -> None:
#     """
#     Delete npat child resource. See https://docs.kopf.dev/en/stable/hierarchies/#owner-references for how to mark ownership of child resources.
#     """