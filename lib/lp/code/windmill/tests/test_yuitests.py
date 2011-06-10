# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run YUI.test tests."""

__metaclass__ = type
__all__ = []

from lp.code.windmill.testing import CodeYUITestLayer
from lp.testing import (
    build_yui_unittest_suite,
    YUIUnitTestCase,
    )


class CodeYUIUnitTestCase(YUIUnitTestCase):

    layer = CodeYUITestLayer
    suite_name = 'CodeYUIUnitTests'


def test_suite():
    app_testing_path = 'lp/code/javascript/tests'
    return build_yui_unittest_suite(app_testing_path, CodeYUIUnitTestCase)
