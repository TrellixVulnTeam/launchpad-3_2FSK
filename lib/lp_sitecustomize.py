# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# This file is imported by parts/scripts/sitecustomize.py, as set up in our
# buildout.cfg (see the "initialization" key in the "[scripts]" section).

import os
from lp.services.mime import customizeMimetypes
from zope.security import checker
from bzrlib.branch import BzrBranch7

def main():
    # Note that we configure the LPCONFIG environmental variable in the
    # custom buildout-generated sitecustomize.py in
    # parts/scripts/sitecustomize.py rather than here.  This is because
    # the instance name, ${configuration:instance_name}, is dynamic,
    # sent to buildout from the Makefile.  See buildout.cfg in the
    # initialization value of the [scripts] section for the code that
    # goes into this custom sitecustomize.py.  We do as much other
    # initialization as possible here, in a more visible place.
    os.environ['STORM_CEXTENSIONS'] = '1'
    customizeMimetypes()
    checker.BasicTypes.update({BzrBranch7: checker.NoProxy})

main()
