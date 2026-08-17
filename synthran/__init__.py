"""SynthRAN experiment orchestration package."""

from __future__ import annotations

from importlib import import_module
import sys

__version__ = "0.0.1"


def _module_alias(name: str, target: str) -> None:
    """Keep existing import contracts while implementation lives in domain packages."""

    sys.modules[f"{__name__}.{name}"] = import_module(target)


# Domain modules live under experiment/, network/, and research/. These aliases
# preserve existing Python import contracts without retaining duplicate source files.
_module_alias("experiment_resources", "synthran.experiment.resources")
_module_alias("network_runtime", "synthran.network.runtime")
_module_alias("rfsim_runtime", "synthran.network.rfsim")
_module_alias("experiment_runtime", "synthran.experiment.runtime")
_module_alias("resource_runtime", "synthran.network.resources")
_module_alias("research_collector", "synthran.research.collector")
_module_alias("research_iperf", "synthran.research.iperf")
_module_alias("research_instrumentation", "synthran.research.instrumentation")
_module_alias("research_sampling", "synthran.research.sampling")
_module_alias("research_runtime", "synthran.research.runtime")
