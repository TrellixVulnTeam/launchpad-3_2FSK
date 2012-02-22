# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

__metaclass__ = type

import datetime
from StringIO import StringIO
import time

from zope.component import getUtility
from zope.interface import Interface
from zope.schema.interfaces import TooShort

from lp.app.validators import LaunchpadValidationError
from lp.blueprints.enums import SpecificationWorkItemStatus
from lp.registry.interfaces.nameblacklist import INameBlacklistSet
from lp.registry.interfaces.person import (
    CLOSED_TEAM_POLICY,
    OPEN_TEAM_POLICY,
    )
from lp.services.database.lpstorm import IStore
from lp.services.fields import (
    BaseImageUpload,
    BlacklistableContentNameField,
    FormattableDate,
    is_public_person_or_closed_team,
    StrippableText,
    )
from lp.testing import (
    login_person,
    TestCase,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


def make_target():
    """Make a trivial object to be a target of the field setting."""

    class Simple:
        """A simple class to test setting fields on."""

    return Simple()


class TestFormattableDate(TestCase):

    def test_validation_fails_on_bad_data(self):
        field = FormattableDate()
        date_value = datetime.date(
            *(time.strptime('1000-01-01', '%Y-%m-%d'))[:3])
        self.assertRaises(
            LaunchpadValidationError, field.validate, date_value)

    def test_validation_passes_good_data(self):
        field = FormattableDate()
        date_value = datetime.date(
            *(time.strptime('2010-01-01', '%Y-%m-%d'))[:3])
        self.assertIs(None, field.validate(date_value))


class TestStrippableText(TestCase):

    def test_strips_text(self):
        # The set method should strip the string before setting the field.
        target = make_target()
        field = StrippableText(__name__='test', strip_text=True)
        self.assertTrue(field.strip_text)
        field.set(target, '  testing  ')
        self.assertEqual('testing', target.test)

    def test_strips_text_trailing_only(self):
        # The set method strips the trailing whitespace.
        target = make_target()
        field = StrippableText(
            __name__='test', strip_text=True, trailing_only=True)
        self.assertTrue(field.trailing_only)
        field.set(target, '  testing  ')
        self.assertEqual('  testing', target.test)

    def test_default_constructor(self):
        # If strip_text is not set, or set to false, then the text is not
        # stripped when set.
        target = make_target()
        field = StrippableText(__name__='test')
        self.assertFalse(field.strip_text)
        field.set(target, '  testing  ')
        self.assertEqual('  testing  ', target.test)

    def test_setting_with_none(self):
        # The set method is given None, the attribute is set to None
        target = make_target()
        field = StrippableText(__name__='test', strip_text=True)
        field.set(target, None)
        self.assertIs(None, target.test)

    def test_validate_min_contraints(self):
        # The minimum length constraint tests the stripped string.
        field = StrippableText(
            __name__='test', strip_text=True, min_length=1)
        self.assertRaises(TooShort, field.validate, u'  ')

    def test_validate_max_contraints(self):
        # The minimum length constraint tests the stripped string.
        field = StrippableText(
            __name__='test', strip_text=True, max_length=2)
        self.assertEqual(None, field.validate(u'  a  '))


class WorkItemParseError(Exception):
    """An error when parsing a work item line from a blueprint."""


import re
from zope.schema import Text
from lp.registry.interfaces.person import IPersonSet
class WorkItemsText(Text):

    def parse_line(self, line):
        assert line.strip() != '', "Please don't give us an empty line"
        try:
            title, status = line.rsplit(':')
        except ValueError:
            raise WorkItemParseError('Missing work item status.')
            
        status = status.strip().lower()

        assignee = None
        if title.startswith('['):
            if ']' in title:
                off = title.index(']')
                assignee = title[1:off]
                title = title[off + 1:].strip()
            else:
                raise WorkItemParseError('Missing closing "]" for assignee')

        if title == '':
            raise WorkItemParseError(
                'No work item title found on "%s"' % line)

        valid_statuses = SpecificationWorkItemStatus.items
        if status not in [item.name.lower() for item in valid_statuses]:
            raise WorkItemParseError('Unknown status: %s' % status)
        status = valid_statuses[status.upper()]

        return {'title': title, 'status': status, 'assignee': assignee}

    def parse(self, text):
        milestone = None
        work_items = []
        milestone_re = re.compile('^work items(.*)\s*:\s*$', re.I)
        for line in text.splitlines():
            if line.strip() == '':
                continue
            milestone_match = milestone_re.search(line)
            if milestone_match:
                milestone_part = milestone_match.group(1).strip()
                milestone = milestone_part.split()[-1]
            else:
                new_work_item = self.parse_line(line)
                new_work_item['milestone'] = milestone
                work_items.append(new_work_item)
        return work_items

    def validate(self, work_item):
        assignee_name = work_item['assignee']
        if assignee_name is not None:
            assignee = getUtility(IPersonSet).getByName(assignee_name)
            if assignee is None:
                raise ValueError("Unknown person name: %s" % assignee_name)
        else:
            assignee = None


class TestWorkItemsTextValidation(TestCase):

    layer = DatabaseFunctionalLayer

    def test_person_is_looked_up(self):
        field = WorkItemsText(__name__='test')
        person_name = 'test-person'
        work_item = {'title': 'A work item',
                     'status': SpecificationWorkItemStatus.TODO,
                     'assignee': person_name,
                     'milestone': None}
        
        self.assertRaises(
            ValueError, field.validate, work_item)


class TestWorkItemsText(TestCase):

    def test_single_line_parsing(self):
        field = WorkItemsText(__name__='test')
        work_items_title = 'Test this work item'
        parsed = field.parse_line('%s: TODO' % (work_items_title))
        self.assertEqual(parsed['title'], work_items_title)
        self.assertEqual(parsed['status'], SpecificationWorkItemStatus.TODO)

    def test_silly_caps_status_parsing(self):
        field = WorkItemsText(__name__='test')
        parsed_upper = field.parse_line('Test this work item: TODO    ')
        self.assertEqual(parsed_upper['status'], SpecificationWorkItemStatus.TODO)
        parsed_lower = field.parse_line('Test this work item:     todo')
        self.assertEqual(parsed_lower['status'], SpecificationWorkItemStatus.TODO)
        parsed_camel = field.parse_line('Test this work item: ToDo')
        self.assertEqual(parsed_camel['status'], SpecificationWorkItemStatus.TODO)

    def test_parse_line_without_status_fails(self):
        # We should require an explicit status to avoid the problem of work
        # items with a url but no status.
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            WorkItemParseError, field.parse_line,
            'Missing status')

    def test_parse_line_without_title_fails(self):
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            WorkItemParseError, field.parse_line,
            ':TODO')

    def test_parse_line_without_title_with_assignee_fails(self):
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            WorkItemParseError, field.parse_line,
            '[test-person] :TODO')

    def test_multi_line_parsing(self):
        field = WorkItemsText(__name__='test')
        title_1 = 'Work item 1'
        title_2 = 'Work item 2'
        work_items_text = "%s: TODO\n%s: POSTPONED" % (title_1, title_2)
        parsed = field.parse(work_items_text)
        self.assertEqual(
            parsed, [{'title': title_1,
                      'status': SpecificationWorkItemStatus.TODO,
                      'assignee': None,
                      'milestone': None},
                     {'title': title_2,
                      'status': SpecificationWorkItemStatus.POSTPONED,
                      'assignee': None,
                      'milestone': None}])

    def test_parse_assignee(self):
        field = WorkItemsText(__name__='test')
        title = 'Work item 1'
        assignee = 'test-person'
        work_items_text = "[%s]%s: TODO" % (assignee, title)
        parsed = field.parse_line(work_items_text)
        self.assertEqual(parsed['assignee'], assignee)

    def test_parse_assignee_with_space(self):
        field = WorkItemsText(__name__='test')
        title = 'Work item 1'
        assignee = 'test-person'
        work_items_text = "[%s] %s: TODO" % (assignee, title)
        parsed = field.parse_line(work_items_text)
        self.assertEqual(parsed['assignee'], assignee)

    def test_parse_line_with_missing_closing_bracket_for_assignee(self):
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            WorkItemParseError, field.parse_line,
            "[test-person A single work item: TODO")

    def test_parse_line_with_invalid_status(self):
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            WorkItemParseError, field.parse_line,
            'Invalid status: FOO')

    def test_parse_empty_line_raises(self):
        field = WorkItemsText(__name__='test')
        self.assertRaises(
            AssertionError, field.parse_line, "  \t \t ")

    def test_parse_empty_lines_have_no_meaning(self):
        field = WorkItemsText(__name__='test')
        parsed = field.parse("\n\n\n\n\n\n\n\n")
        self.assertEqual(parsed, [])

    def test_parse_milestone(self):
        field = WorkItemsText(__name__='test')
        milestone = '2012.02'
        title = "Work item for a milestone"
        work_items_text = "Work items for %s:\n%s: TODO" % (milestone, title)
        parsed = field.parse(work_items_text)
        self.assertEqual(parsed, [{'title': title,
                      'status': SpecificationWorkItemStatus.TODO,
                      'assignee': None, 'milestone': milestone}])
        
    def test_parse_multi_milestones(self):
        field = WorkItemsText(__name__='test')
        milestone_1 = '2012.02'
        milestone_2 = '2012.03'
        title_1 = "Work item for a milestone"
        title_2 = "Work item for a later milestone"
        work_items_text = ("Work items for %s:\n%s: POSTPONED\n\nWork items "
                           "for %s:\n%s: TODO" % (milestone_1, title_1,
                                                  milestone_2, title_2))
        parsed = field.parse(work_items_text)
        self.assertEqual(parsed, [{'title': title_1,
                      'status': SpecificationWorkItemStatus.POSTPONED,
                      'assignee': None, 'milestone': milestone_1},
                                  {'title': title_2,
                      'status': SpecificationWorkItemStatus.TODO,
                      'assignee': None, 'milestone': milestone_2}])

    def test_parse_orphaned_work_items(self):
        # Work items not in a milestone block belong to the latest specified 
        # milestone.
        field = WorkItemsText(__name__='test')
        milestone_1 = '2012.02'
        milestone_2 = '2012.03'
        title_1 = "Work item for a milestone"
        title_2 = "Work item for a later milestone"
        title_3 = "A work item preceeded by a blank line"
        work_items_text = ("Work items for %s:\n%s: POSTPONED\n\nWork items "
                           "for %s:\n%s: TODO\n\n%s: TODO" % (milestone_1, title_1,
                                                  milestone_2, title_2, title_3))
        parsed = field.parse(work_items_text)
        self.assertEqual(parsed, 
                         [{'title': title_1,
                           'status': SpecificationWorkItemStatus.POSTPONED,
                           'assignee': None, 'milestone': milestone_1},
                          {'title': title_2,
                           'status': SpecificationWorkItemStatus.TODO,
                           'assignee': None, 'milestone': milestone_2},
                          {'title': title_3,
                           'status': SpecificationWorkItemStatus.TODO,
                           'assignee': None, 'milestone': milestone_2}])


    # XXX: add tests for sequence
    # XXX: add tests for looking up people in set()
    # XXX: add tests for looking up milestones in set() and check that they are valid for that bp

class TestBlacklistableContentNameField(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestBlacklistableContentNameField, self).setUp()
        name_blacklist_set = getUtility(INameBlacklistSet)
        self.team = self.factory.makeTeam()
        admin_exp = name_blacklist_set.create(u'fnord', admin=self.team)
        IStore(admin_exp).flush()

    def makeTestField(self):
        """Return testible subclass."""

        class ITestInterface(Interface):
            pass

        class TestField(BlacklistableContentNameField):
            _content_iface = ITestInterface

            def _getByName(self, name):
                return None

        return TestField(__name__='test')

    def test_validate_fails_with_blacklisted_name_anonymous(self):
        # Anonymous users, processes, cannot create a name that matches
        # a blacklisted name.
        field = self.makeTestField()
        date_value = u'fnord'
        self.assertRaises(
            LaunchpadValidationError, field.validate, date_value)

    def test_validate_fails_with_blacklisted_name_not_admin(self):
        # Users who do not adminster a blacklisted name cannot create
        # a matching name.
        field = self.makeTestField()
        date_value = u'fnord'
        login_person(self.factory.makePerson())
        self.assertRaises(
            LaunchpadValidationError, field.validate, date_value)

    def test_validate_passes_for_admin(self):
        # Users in the team that adminsters a blacklisted name may create
        # matching names.
        field = self.makeTestField()
        date_value = u'fnord'
        login_person(self.team.teamowner)
        self.assertEqual(None, field.validate(date_value))


class TestBaseImageUpload(TestCase):
    """Test for the BaseImageUpload field."""

    class ExampleImageUpload(BaseImageUpload):
        dimensions = (192, 192)
        max_size = 100 * 1024

    def test_validation_corrupt_image(self):
        # ValueErrors raised by PIL become LaunchpadValidationErrors.
        field = self.ExampleImageUpload(default_image_resource='dummy')
        image = StringIO(
            '/* XPM */\n'
            'static char *pixmap[] = {\n'
            '"32 32 253 2",\n'
            '  "00 c #01CAA3",\n'
            '  ".. s None c None",\n'
            '};')
        image.filename = 'foo.xpm'
        self.assertRaises(
            LaunchpadValidationError, field.validate, image)

    def test_validation_non_image(self):
        # IOError raised by PIL become LaunchpadValidationErrors.
        field = self.ExampleImageUpload(default_image_resource='dummy')
        image = StringIO('foo bar bz')
        image.filename = 'foo.jpg'
        self.assertRaises(
            LaunchpadValidationError, field.validate, image)


class Test_is_person_or_closed_team(TestCaseWithFactory):
    """ Tests for is_person_or_closed_team()."""

    layer = DatabaseFunctionalLayer

    def test_non_person(self):
        self.assertFalse(is_public_person_or_closed_team(0))

    def test_person(self):
        person = self.factory.makePerson()
        self.assertTrue(is_public_person_or_closed_team(person))

    def test_open_team(self):
        for policy in OPEN_TEAM_POLICY:
            open_team = self.factory.makeTeam(subscription_policy=policy)
            self.assertFalse(
                is_public_person_or_closed_team(open_team),
                "%s is not open" % policy)

    def test_closed_team(self):
        for policy in CLOSED_TEAM_POLICY:
            closed_team = self.factory.makeTeam(subscription_policy=policy)
            self.assertTrue(
                is_public_person_or_closed_team(closed_team),
                "%s is not closed" % policy)
