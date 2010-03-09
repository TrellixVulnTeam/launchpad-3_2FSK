# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0401,C0301

__metaclass__ = type

# XXX flacoste 2009/03/18 We should use specific imports instead of
# importing from this module.

from canonical.launchpad.interfaces.launchpad import *
from lp.bugs.interfaces.malone import *
from canonical.launchpad.interfaces.validation import *

# these need to be at the top, because the others depend on them sometimes
from lp.registry.interfaces.person import *
from lp.registry.interfaces.pillar import *

from canonical.launchpad.interfaces.account import *
from lp.soyuz.interfaces.archive import *
from lp.soyuz.interfaces.archivedependency import *
from lp.soyuz.interfaces.archivepermission import *
from lp.soyuz.interfaces.archivesubscriber import *
from lp.registry.interfaces.announcement import *
from canonical.launchpad.interfaces.authserver import *
from canonical.launchpad.interfaces.authtoken import *
from lp.soyuz.interfaces.binarypackagerelease import *
from lp.soyuz.interfaces.binarypackagename import *
from lp.bugs.interfaces.bugactivity import *
from lp.bugs.interfaces.bugattachment import *
from lp.bugs.interfaces.bug import *
from lp.bugs.interfaces.bugbranch import *
from lp.bugs.interfaces.bugcve import *
from lp.bugs.interfaces.buglink import *
from lp.bugs.interfaces.bugmessage import *
from lp.bugs.interfaces.bugnomination import *
from lp.bugs.interfaces.bugnotification import *
from lp.bugs.interfaces.bugsubscription import *
from lp.bugs.interfaces.bugsupervisor import *
from lp.bugs.interfaces.bugtask import *
from lp.bugs.interfaces.bugtarget import *
from lp.bugs.interfaces.bugtracker import *
from lp.bugs.interfaces.bugwatch import *
from lp.soyuz.interfaces.build import *
from lp.buildmaster.interfaces.builder import *
from lp.soyuz.interfaces.buildrecords import *
from lp.soyuz.interfaces.buildqueue import *
from lp.registry.interfaces.codeofconduct import *
from lp.registry.interfaces.commercialsubscription import *
from lp.soyuz.interfaces.component import *
from lp.services.worlddata.interfaces.country import *
from lp.bugs.interfaces.cve import *
from lp.bugs.interfaces.cvereference import *
from lp.registry.interfaces.distribution import *
from lp.registry.interfaces.distributionmirror import *
from lp.registry.interfaces.distributionsourcepackage import *
from lp.soyuz.interfaces.distributionsourcepackagecache import *
from lp.soyuz.interfaces.distributionsourcepackagerelease import *
from lp.registry.interfaces.series import *
from lp.soyuz.interfaces.distroarchseries import *
from lp.soyuz.interfaces.distroarchseriesbinarypackage import *
from lp.soyuz.interfaces.distroarchseriesbinarypackagerelease\
    import *
from lp.registry.interfaces.distroseries import *
from lp.soyuz.interfaces.distroseriesbinarypackage import *
from lp.soyuz.interfaces.distroseriespackagecache import *
from lp.soyuz.interfaces.distroseriessourcepackagerelease import *
from canonical.launchpad.interfaces.emailaddress import *
from lp.registry.interfaces.entitlement import *
from lp.bugs.interfaces.externalbugtracker import *
from lp.registry.interfaces.featuredproject import *
from lp.soyuz.interfaces.files import *
from canonical.launchpad.interfaces.geoip import *
from lp.registry.interfaces.gpg import *
from canonical.launchpad.interfaces.gpghandler import *
from lp.hardwaredb.interfaces.hwdb import *
from lp.registry.interfaces.irc import *
from lp.registry.interfaces.jabber import *
from lp.registry.interfaces.karma import *
from lp.services.worlddata.interfaces.language import *
from canonical.launchpad.interfaces.launchpad import *
from canonical.launchpad.interfaces.launchpadstatistic import *
from canonical.launchpad.interfaces.librarian import *
from lp.registry.interfaces.location import *
from canonical.launchpad.interfaces.logintoken import *
from canonical.launchpad.interfaces.lpstorm import *
from canonical.launchpad.interfaces.mail import *
from canonical.launchpad.interfaces.mailbox import *
from lp.registry.interfaces.mailinglist import *
from lp.registry.interfaces.mailinglistsubscription import *
from lp.registry.interfaces.mentoringoffer import *
from canonical.launchpad.interfaces.message import *
from lp.registry.interfaces.milestone import *
from canonical.launchpad.interfaces.oauth import *
from canonical.launchpad.interfaces.openidconsumer import *
from canonical.launchpad.interfaces.packagerelationship import *
from canonical.launchpad.interfaces.pathlookup import *
from lp.registry.interfaces.poll import *
from lp.soyuz.interfaces.processor import *
from lp.registry.interfaces.product import *
from lp.registry.interfaces.productlicense import *
from lp.registry.interfaces.productrelease import *
from lp.registry.interfaces.productseries import *
from lp.registry.interfaces.projectgroup import *
from lp.soyuz.interfaces.publishedpackage import *
from lp.soyuz.interfaces.publishing import *
from lp.soyuz.interfaces.queue import *
from lp.registry.interfaces.salesforce import *
from canonical.launchpad.interfaces.schema import *
from lp.services.scripts.interfaces.scriptactivity import *
from lp.soyuz.interfaces.section import *
from canonical.launchpad.interfaces.searchservice import *
from lp.registry.interfaces.sourcepackage import *
from lp.registry.interfaces.sourcepackagename import *
from lp.soyuz.interfaces.sourcepackagerelease import *
from lp.services.worlddata.interfaces.spokenin import *
from lp.registry.interfaces.ssh import *
from lp.registry.interfaces.structuralsubscription import *
from lp.registry.interfaces.teammembership import *
from canonical.launchpad.interfaces.temporaryblobstorage import *
from lp.registry.interfaces.wikiname import *
from lp.soyuz.interfaces.packagediff import *
from lp.soyuz.interfaces.packageset import *


from canonical.launchpad.interfaces._schema_circular_imports import *

