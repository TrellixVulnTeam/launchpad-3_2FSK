# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""
Set the PYTHONPATH for database setup and maintenance scripts
"""
__metaclass__ = type

import sys, os, os.path

# Main lib directory.
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, 'lib',
    ))
# So we can import replication.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))

