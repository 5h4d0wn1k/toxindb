"""Allow `python -m toxindb`."""
import sys
from .cli import main

sys.exit(main())
