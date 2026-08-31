"""``python -m application ...`` 入口。"""

import sys

from application.cli import main

if __name__ == "__main__":
    sys.exit(main())
