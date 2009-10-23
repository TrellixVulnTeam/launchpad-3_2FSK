# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0401

"""Launchpad Browser-Interface View classes.

This is the module to import for Launchpad View Classes. The classes are not
located in this specific module, but are in turn imported from each of the
files in this directory.
"""

# XXX flacoste 2009/03/18 We should use specific imports instead of
# importing from this module.
from lp.soyuz.browser.archive import *
from lp.code.browser.bazaar import *
from lp.soyuz.browser.binarypackagerelease import *
from lp.code.browser.branchmergeproposal import *
from lp.code.browser.branchref import *
from lp.code.browser.branchsubscription import *
from lp.code.browser.branchvisibilitypolicy import *
from lp.soyuz.browser.build import *
from lp.soyuz.browser.builder import *
from lp.code.browser.codeimport import *
from lp.code.browser.codeimportmachine import *
from lp.registry.browser.codeofconduct import *
from lp.code.browser.codereviewcomment import *
from lp.registry.browser.distributionmirror import *
from lp.soyuz.browser.distributionsourcepackagerelease import *
from lp.soyuz.browser.distroarchseries import *
from lp.soyuz.browser.distroarchseriesbinarypackage import *
from lp.soyuz.browser.distroarchseriesbinarypackagerelease import *
from lp.soyuz.browser.distroseriesbinarypackage import *
from lp.soyuz.browser.distroseriessourcepackagerelease import *
from lp.answers.browser.faq import *
from lp.answers.browser.faqcollection import *
from lp.answers.browser.faqtarget import *
from lp.registry.browser.featuredproject import *
from canonical.launchpad.browser.feeds import *
from canonical.launchpad.browser.hwdb import *
from lp.registry.browser.karma import *
from canonical.launchpad.browser.launchpad import *
from canonical.launchpad.browser.launchpadstatistic import *
from canonical.launchpad.browser.librarian import *
from canonical.launchpad.browser.logintoken import *
from lp.registry.browser.mailinglists import *
from lp.registry.browser.mentoringoffer import *
from canonical.launchpad.browser.oauth import *
from canonical.launchpad.browser.objectreassignment import *
from canonical.launchpad.browser.packagerelationship import *
from lp.registry.browser.peoplemerge import *
from lp.registry.browser.poll import *
from lp.soyuz.browser.publishedpackage import *
from lp.soyuz.browser.publishing import *
from lp.answers.browser.question import *
from lp.answers.browser.questiontarget import *
from lp.soyuz.browser.queue import *
from lp.soyuz.browser.sourcepackagerelease import *
from lp.blueprints.browser.specificationbranch import *
from lp.blueprints.browser.specificationdependency import *
from lp.blueprints.browser.specificationfeedback import *
from lp.blueprints.browser.specificationgoal import *
from lp.blueprints.browser.specificationsubscription import *
from lp.blueprints.browser.specificationtarget import *
from lp.blueprints.browser.sprint import *
from lp.blueprints.browser.sprintattendance import *
from lp.blueprints.browser.sprintspecification import *
from lp.registry.browser.team import *
from lp.registry.browser.teammembership import *
from canonical.launchpad.browser.temporaryblobstorage import *
from canonical.launchpad.browser.widgets import *
