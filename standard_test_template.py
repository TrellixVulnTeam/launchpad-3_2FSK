# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Module docstring goes here."""

__metaclass__ = type

import unittest


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

