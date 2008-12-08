# Copyright 2008 Canonical Ltd.  All rights reserved.

"""In-memory doubles of core codehosting objects."""

__metaclass__ = type
__all__ = [
    'InMemoryFrontend',
    'XMLRPCWrapper'
    ]

from xmlrpclib import Fault

from bzrlib.urlutils import escape, unescape

from canonical.database.constants import UTC_NOW
from canonical.launchpad.interfaces.branch import BranchType, IBranch
from canonical.launchpad.interfaces.codehosting import (
    BRANCH_TRANSPORT, CONTROL_TRANSPORT, NOT_FOUND_FAULT_CODE,
    PERMISSION_DENIED_FAULT_CODE)
from canonical.launchpad.testing import ObjectFactory
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.xmlrpc.codehosting import (
    datetime_from_tuple, LAUNCHPAD_SERVICES, iter_split)
from canonical.launchpad.xmlrpc import faults


class FakeStore:
    """Fake store that implements find well enough to pass tests.

    This is needed because some of the `test_codehosting` tests use
    assertSqlAttributeEqualsDate, which relies on ORM behaviour. Here, we fake
    enough of the ORM to pass the tests.
    """

    def __init__(self, object_set):
        self._object_set = object_set

    def find(self, cls, **kwargs):
        """Implement Store.find that takes two attributes: id and one other.

        This is called by `assertSqlAttributeEqualsDate`, which relies on
        `find` returning either a single match or None. Returning a match
        implies that the given attribute has the expected value. Returning
        None implies the opposite.
        """
        branch_id = kwargs.pop('id')
        assert len(kwargs) == 1, (
            'Expected only id and one other. Got %r' % kwargs)
        attribute = kwargs.keys()[0]
        expected_value = kwargs[attribute]
        branch = self._object_set.get(branch_id)
        if branch is None:
            return None
        if expected_value is getattr(branch, attribute):
            return branch
        return None


class FakeDatabaseObject:
    """Base class for fake database objects."""

    def _set_object_set(self, object_set):
        self.__storm_object_info__ = {'store': FakeStore(object_set)}


class ObjectSet:
    """Generic set of database objects."""

    def __init__(self):
        self._objects = {}
        self._next_id = 1

    def _add(self, db_object):
        self._objects[self._next_id] = db_object
        db_object.id = self._next_id
        self._next_id += 1
        db_object._set_object_set(self)
        return db_object

    def _delete(self, db_object):
        del self._objects[db_object.id]

    def __iter__(self):
        return self._objects.itervalues()

    def _find(self, **kwargs):
        [(key, value)] = kwargs.items()
        for obj in self:
            if getattr(obj, key) == value:
                return obj

    def get(self, id):
        return self._objects.get(id, None)

    def getByName(self, name):
        return self._find(name=name)


class FakeBranch(FakeDatabaseObject):
    """Fake branch object."""

    def __init__(self, branch_type, name, owner, url=None, product=None,
                 stacked_on=None, private=False, registrant=None):
        self.branch_type = branch_type
        self.last_mirror_attempt = None
        self.last_mirrored = None
        self.last_mirrored_id = None
        self.next_mirror_time = None
        self.url = url
        self.mirror_failures = 0
        self.name = name
        self.owner = owner
        self.stacked_on = None
        self.mirror_status_message = None
        self.stacked_on = stacked_on
        self.private = private
        self.product = product
        self.registrant = registrant
        self._mirrored = False

    @property
    def unique_name(self):
        if self.product is None:
            product = '+junk'
        else:
            product = self.product.name
        return '~%s/%s/%s' % (self.owner.name, product, self.name)

    def getPullURL(self):
        pass

    def startMirroring(self):
        pass

    def mirrorComplete(self, rev_id):
        self._mirrored = True

    def requestMirror(self):
        self.next_mirror_time = UTC_NOW


class FakePerson(FakeDatabaseObject):
    """Fake person object."""

    def __init__(self, name):
        self.name = self.displayname = name

    def isTeam(self):
        return False

    def inTeam(self, person_or_team):
        if self is person_or_team:
            return True
        if not person_or_team.isTeam():
            return False
        return self in person_or_team._members


class FakeTeam(FakePerson):
    """Fake team."""

    def __init__(self, name, members=None):
        super(FakeTeam, self).__init__(name)
        if members is None:
            self._members = []
        else:
            self._members = list(members)

    def isTeam(self):
        return True


class FakeProduct(FakeDatabaseObject):
    """Fake product."""

    def __init__(self, name):
        self.name = name
        self.development_focus = FakeProductSeries()

    @property
    def default_stacked_on_branch(self):
        b = self.development_focus.user_branch
        if b is None:
            return None
        elif b._mirrored:
            return b
        else:
            return None


class FakeProductSeries(FakeDatabaseObject):
    """Fake product series."""

    user_branch = None


class FakeScriptActivity(FakeDatabaseObject):
    """Fake script activity."""

    def __init__(self, name, hostname, date_started, date_completed):
        self.id = self.name = name
        self.hostname = hostname
        self.date_started = datetime_from_tuple(date_started)
        self.date_completed = datetime_from_tuple(date_completed)


DEFAULT_PRODUCT = object()


class FakeObjectFactory(ObjectFactory):

    def __init__(self, branch_set, person_set, product_set):
        super(FakeObjectFactory, self).__init__()
        self._branch_set = branch_set
        self._person_set = person_set
        self._product_set = product_set

    def makeBranch(self, branch_type=None, stacked_on=None, private=False,
                   product=DEFAULT_PRODUCT, owner=None, name=None,
                   registrant=None):
        if branch_type == BranchType.MIRRORED:
            url = self.getUniqueURL()
        else:
            url = None
        if name is None:
            name = self.getUniqueString()
        if owner is None:
            owner = self.makePerson()
        if product is DEFAULT_PRODUCT:
            product = self.makeProduct()
        if registrant is None:
            registrant = self.makePerson()
        IBranch['name'].validate(unicode(name))
        branch = FakeBranch(
            branch_type, name=name, owner=owner, url=url,
            stacked_on=stacked_on, product=product, private=private,
            registrant=registrant)
        self._branch_set._add(branch)
        return branch

    def makeTeam(self, owner):
        team = FakeTeam(name=self.getUniqueString(), members=[owner])
        self._person_set._add(team)
        return team

    def makePerson(self):
        person = FakePerson(name=self.getUniqueString())
        self._person_set._add(person)
        return person

    def makeProduct(self):
        product = FakeProduct(self.getUniqueString())
        self._product_set._add(product)
        return product


class FakeBranchPuller:

    def __init__(self, branch_set, script_activity_set):
        self._branch_set = branch_set
        self._script_activity_set = script_activity_set

    def _getBranchPullInfo(self, branch):
        default_branch = ''
        if branch.product is not None:
            series = branch.product.development_focus
            user_branch = series.user_branch
            if (user_branch is not None
                and not (
                    user_branch.private
                    and branch.branch_type == BranchType.MIRRORED)):
                default_branch = '/' + user_branch.unique_name
        return (
            branch.id, branch.getPullURL(), branch.unique_name,
            default_branch)

    def getBranchPullQueue(self, branch_type):
        queue = []
        branch_type = BranchType.items[branch_type]
        for branch in self._branch_set:
            if (branch.branch_type == branch_type
                and branch.next_mirror_time < UTC_NOW):
                queue.append(self._getBranchPullInfo(branch))
        return queue

    def startMirroring(self, branch_id):
        branch = self._branch_set.get(branch_id)
        if branch is None:
            return faults.NoBranchWithID(branch_id)
        branch.last_mirror_attempt = UTC_NOW
        branch.next_mirror_time = None
        return True

    def mirrorComplete(self, branch_id, last_revision_id):
        branch = self._branch_set.get(branch_id)
        if branch is None:
            return faults.NoBranchWithID(branch_id)
        branch.last_mirrored_id = last_revision_id
        branch.last_mirrored = UTC_NOW
        branch.mirror_failures = 0
        for stacked_branch in self._branch_set:
            if stacked_branch.stacked_on is branch:
                stacked_branch.requestMirror()
        return True

    def mirrorFailed(self, branch_id, reason):
        branch = self._branch_set.get(branch_id)
        if branch is None:
            return faults.NoBranchWithID(branch_id)
        branch.mirror_failures += 1
        branch.mirror_status_message = reason
        return True

    def recordSuccess(self, name, hostname, date_started, date_completed):
        self._script_activity_set._add(
            FakeScriptActivity(name, hostname, date_started, date_completed))
        return True

    def setStackedOn(self, branch_id, stacked_on_location):
        branch = self._branch_set.get(branch_id)
        if branch is None:
            return faults.NoBranchWithID(branch_id)
        if stacked_on_location == '':
            branch.stacked_on = None
            return True
        stacked_on_location = stacked_on_location.rstrip('/')
        for stacked_on_branch in self._branch_set:
            if stacked_on_location == stacked_on_branch.url:
                branch.stacked_on = stacked_on_branch
                break
            if stacked_on_location == '/' + stacked_on_branch.unique_name:
                branch.stacked_on = stacked_on_branch
                break
        else:
            return faults.NoSuchBranch(stacked_on_location)
        return True


class FakeBranchFilesystem:

    def __init__(self, branch_set, person_set, product_set, factory):
        self._branch_set = branch_set
        self._person_set = person_set
        self._product_set = product_set
        self._factory = factory

    def createBranch(self, requester_id, branch_path):
        if not branch_path.startswith('/'):
            return faults.InvalidPath(branch_path)
        try:
            escaped_path = unescape(branch_path.strip('/')).encode('utf-8')
            branch_tokens = escaped_path.split('/')
            owner_name, product_name, branch_name = branch_tokens
        except ValueError:
            return Fault(
                PERMISSION_DENIED_FAULT_CODE,
                "Cannot create branch at '%s'" % branch_path)
        owner_name = owner_name[1:]
        owner = self._person_set.getByName(owner_name)
        if owner is None:
            return Fault(
                NOT_FOUND_FAULT_CODE,
                "User/team %r does not exist." % (owner_name,))
        registrant = self._person_set.get(requester_id)
        # The real code consults the branch creation policy of the product. We
        # don't need to do so here, since the tests above this layer never
        # encounter that behaviour. If they *do* change to rely on the branch
        # creation policy, the observed behaviour will be failure to raise
        # exceptions.
        if not registrant.inTeam(owner):
            return Fault(
                PERMISSION_DENIED_FAULT_CODE,
                ('%s cannot create branches owned by %s'
                 % (registrant.displayname, owner.displayname)))
        if product_name == '+junk':
            if owner.isTeam():
                return Fault(
                    PERMISSION_DENIED_FAULT_CODE,
                    'Cannot create team-owned junk branches.')
            product = None
        else:
            product = self._product_set.getByName(product_name)
            if product is None:
                return Fault(
                    NOT_FOUND_FAULT_CODE,
                    "Project %r does not exist." % (product_name,))
        try:
            return self._factory.makeBranch(
                owner=owner, name=branch_name, product=product,
                registrant=registrant, branch_type=BranchType.HOSTED).id
        except LaunchpadValidationError, e:
            return Fault(PERMISSION_DENIED_FAULT_CODE, str(e))

    def requestMirror(self, requester_id, branch_id):
        self._branch_set.get(branch_id).requestMirror()

    def _canRead(self, person_id, branch):
        """Can the person 'person_id' see 'branch'?"""
        # This is a substitute for an actual launchpad.View check on the
        # branch. It doesn't have to match the behaviour exactly, as long as
        # it's stricter than the real implementation (that way, mismatches in
        # behaviour should generate explicit errors.)
        if person_id == LAUNCHPAD_SERVICES:
            return True
        if not branch.private:
            return True
        person = self._person_set.get(person_id)
        return person.inTeam(branch.owner)

    def _canWrite(self, person_id, branch):
        """Can the person 'person_id' write to 'branch'?"""
        if person_id == LAUNCHPAD_SERVICES:
            return False
        if branch.branch_type != BranchType.HOSTED:
            return False
        person = self._person_set.get(person_id)
        return person.inTeam(branch.owner)

    def getBranchInformation(self, requester_id, user_name, product_name,
                             branch_name):
        unique_name = '~%s/%s/%s' % (user_name, product_name, branch_name)
        branch = self._branch_set._find(unique_name=unique_name)
        if branch is None:
            return '', ''
        if not self._canRead(requester_id, branch):
            return '', ''
        if branch.branch_type == BranchType.REMOTE:
            return '', ''
        if self._canWrite(requester_id, branch):
            permission = 'w'
        else:
            permission = 'r'
        return branch.id, permission

    def getDefaultStackedOnBranch(self, requester_id, product_name):
        if product_name == '+junk':
            return ''
        product = self._product_set.getByName(product_name)
        if product is None:
            return Fault(
                NOT_FOUND_FAULT_CODE,
                'Project %r does not exist.' % (product_name,))
        branch = product.development_focus.user_branch
        if branch is None:
            return ''
        if not self._canRead(requester_id, branch):
            return ''
        return '/' + product.development_focus.user_branch.unique_name

    def _serializeControlDirectory(self, requester, product_path,
                                   trailing_path):
        try:
            owner_name, product_name, bazaar = product_path.split('/')
        except ValueError:
            # Wrong number of segments -- can't be a product.
            return
        if bazaar != '.bzr':
            return
        product = self._product_set.getByName(product_name)
        if product is None:
            return
        default_branch = product.default_stacked_on_branch
        if default_branch is None:
            return
        if not self._canRead(requester, default_branch):
            return
        return (
            CONTROL_TRANSPORT,
            {'default_stack_on': escape('/' + default_branch.unique_name)},
            '/'.join([bazaar, trailing_path]))

    def _serializeBranch(self, requester_id, branch, trailing_path):
        if not self._canRead(requester_id, branch):
            return None
        elif branch.branch_type == BranchType.REMOTE:
            return None
        else:
            return (
                BRANCH_TRANSPORT,
                {'id': branch.id,
                 'writable': self._canWrite(requester_id, branch),
                 }, trailing_path)

    def translatePath(self, requester_id, path):
        if not path.startswith('/'):
            return faults.InvalidPath(path)
        stripped_path = path.strip('/')
        for first, second in iter_split(stripped_path, '/'):
            first = unescape(first).encode('utf-8')
            # Is it a branch?
            branch = self._branch_set._find(unique_name=first)
            if branch is not None:
                branch = self._serializeBranch(requester_id, branch, second)
                if branch is None:
                    break
                return branch

            # Is it a product?
            product = self._serializeControlDirectory(
                requester_id, first, second)
            if product:
                return product
        return faults.PathTranslationError(path)


class InMemoryFrontend:
    """A in-memory 'frontend' to Launchpad's branch services.

    This is an in-memory version of `LaunchpadDatabaseFrontend`.
    """

    def __init__(self):
        self._branch_set = ObjectSet()
        self._script_activity_set = ObjectSet()
        self._person_set = ObjectSet()
        self._product_set = ObjectSet()
        self._factory = FakeObjectFactory(
            self._branch_set, self._person_set, self._product_set)
        self._puller = FakeBranchPuller(
            self._branch_set, self._script_activity_set)
        self._branchfs = FakeBranchFilesystem(
            self._branch_set, self._person_set, self._product_set,
            self._factory)

    def getFilesystemEndpoint(self):
        """See `LaunchpadDatabaseFrontend`.

        Return an in-memory implementation of IBranchFileSystem that passes
        the tests in `test_codehosting`.
        """
        return self._branchfs

    def getPullerEndpoint(self):
        """See `LaunchpadDatabaseFrontend`.

        Return an in-memory implementation of IBranchPuller that passes the
        tests in `test_codehosting`.
        """
        return self._puller

    def getLaunchpadObjectFactory(self):
        """See `LaunchpadDatabaseFrontend`.

        Returns a partial, in-memory implementation of LaunchpadObjectFactory
        -- enough to pass the tests.
        """
        return self._factory

    def getBranchSet(self):
        """See `LaunchpadDatabaseFrontend`.

        Returns a partial implementation of `IBranchSet` -- enough to pass the
        tests.
        """
        return self._branch_set

    def getLastActivity(self, activity_name):
        """Get the last script activity with 'activity_name'."""
        return self._script_activity_set.getByName(activity_name)


class XMLRPCWrapper:
    """Wrapper around the endpoints that emulates an XMLRPC client."""

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def callRemote(self, method_name, *args):
        result = getattr(self.endpoint, method_name)(*args)
        if isinstance(result, Fault):
            raise result
        return result
