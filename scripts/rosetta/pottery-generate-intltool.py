#! /usr/bin/python2.5
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Print a list of directories that contain a valid intltool structure."""

import _pythonpath


from lp.translations.pottery.build_slave import generate_pots


if __name__ == "__main__":
    print "\n".join(generate_pots('.'))
