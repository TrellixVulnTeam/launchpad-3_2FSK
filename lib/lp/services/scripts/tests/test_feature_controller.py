# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test feature controller in scripts."""

__metaclass__ = type

from canonical.testing.layers import DatabaseFunctionalLayer
from lp.services.features import (
    get_relevant_feature_controller,
    install_feature_controller,
    )
from lp.services.features.flags import NullFeatureController
from lp.services.features.testing import FeatureFixture
from lp.services.scripts.base import LaunchpadScript
from lp.testing import TestCase
from lp.testing.fakemethod import FakeMethod


class FakeScript(LaunchpadScript):
    """A dummy script that only records which feature controller is active."""

    observed_feature_controller = object()

    def __init__(self, name):
        super(FakeScript, self).__init__(name=name, test_args=[])

    def main(self):
        self.observed_feature_controller = get_relevant_feature_controller()

    # Shortcut some underpinnings of LaunchpadScript.run that we can't
    # afford to have happen in tests.
    _init_zca = FakeMethod()
    _init_db = FakeMethod()
    record_activity = FakeMethod()


class TestScriptFeatureController(TestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestScriptFeatureController, self).setUp()
        self.original_controller = get_relevant_feature_controller()

    def tearDown(self):
        install_feature_controller(self.original_controller)
        super(TestScriptFeatureController, self).tearDown()

    def test_script_installs_script_feature_controller(self):
        script = FakeScript(name="bongo")
        script_feature_controller = get_relevant_feature_controller()
        self.assertNotEqual(
            self.original_controller, script.observed_feature_controller)
        self.assertNotEqual(None, script.observed_feature_controller)

    def test_script_restores_feature_controller(self):
        previous_controller = NullFeatureController()
        install_feature_controller(previous_controller)
        FakeScript(name="mongo").run()
        self.assertEqual(
            previous_controller, get_relevant_feature_controller())
