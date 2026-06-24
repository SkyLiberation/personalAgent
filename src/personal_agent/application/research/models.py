"""Re-export of research domain models, now defined in the kernel contracts.

The model definitions moved to ``personal_agent.kernel.contracts.research`` so the
infra layer (research store) can depend on them without importing the application
``research`` package. This module keeps the historical import path working.
"""

from personal_agent.kernel.contracts.research import *  # noqa: F401,F403
