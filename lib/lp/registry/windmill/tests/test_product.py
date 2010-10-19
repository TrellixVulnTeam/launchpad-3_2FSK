# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test product index page."""

__metaclass__ = type
__all__ = []

import unittest

from canonical.launchpad.windmill.testing import (
    lpuser,
    widgets,
    )
from lp.registry.windmill.testing import RegistryWindmillLayer
from lp.testing import WindmillTestCase


class TestProductIndexPage(WindmillTestCase):
    """Test product index page."""

    layer = RegistryWindmillLayer

    def test_title_inline_edit(self):
        test = widgets.InlineEditorWidgetTest(
            url='http://launchpad.dev:8085/firefox',
            widget_id='product-title',
            expected_value='Mozilla Firefox',
            new_value='The awesome Mozilla Firefox',
            name='test_title_inline_edit',
            suite=__name__,
            user=lpuser.SAMPLE_PERSON)
        test()

    def test_programming_languages_edit(self):
        test = widgets.InlineEditorWidgetTest(
            url='http://launchpad.dev:8085/firefox',
            widget_id='programminglang',
            widget_tag='span',
            expected_value='Not yet specified',
            new_value='C++',
            name='test_proglang_inline_edit',
            suite=__name__,
            user=lpuser.SAMPLE_PERSON)
        test()


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
