"""Public compatibility surface for fail-closed R2Lab resource control.

The implementation lives in :mod:`synthran.network.r2lab_controller`. Keeping
this module as the stable import surface preserves the existing CLI and tests
while the live-evidence-backed controller evolves on the R2Lab integration
branch.
"""

from synthran.network.r2lab_controller import *  # noqa: F403
