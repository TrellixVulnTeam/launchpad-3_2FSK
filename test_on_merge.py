# Copyright 2004 Canonical Ltd.  All rights reserved.

"""Tests that get run automatically on a merge."""

import sys
import os

def main():
    """Call test.py with whatever arguments this script was run with.

    If the tests ran ok (last line of stderr is 'OK<return>') then suppress
    output and exit(0).

    Otherwise, print output and exit(1).
    """
    here = os.path.dirname(os.path.realpath(__file__))
    stdin, out, err = os.popen3('cd %s; python test.py %s < /dev/null' %
        (here, ' '.join(sys.argv[1:])))
    errlines = err.readlines()
    dataout = out.read()
    test_ok = errlines[-1] == 'OK\n'

    if test_ok:
        return 0
    else:
        print '---- test stdout ----'
        print dataout
        print '---- end test stdout ----'

        print '---- test stderr ----'
        print ''.join(errlines)
        print '---- end test stderr ----'
        return 1

if __name__ == '__main__':
    sys.exit(main())
