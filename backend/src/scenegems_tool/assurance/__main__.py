"""python -m scenegems_tool.assurance --api http://127.0.0.1:5174 <command>: campaigns on a control node's operator API."""

import sys

from scenegems_tool.assurance.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
