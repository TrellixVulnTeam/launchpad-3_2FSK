# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0401,C0301

# XXX flacoste 2009/03/18 We should use specific imports instead of
# importing from this module.
from canonical.launchpad.database.account import *
from lp.code.model.codeimport import *
from lp.code.model.codeimportevent import *
from lp.code.model.codeimportjob import *
from lp.code.model.codeimportmachine import *
from lp.code.model.codeimportresult import *
from lp.code.model.codereviewvote import *
from canonical.launchpad.database.customlanguagecode import *
from lp.registry.model.milestone import *
from lp.registry.model.person import *
from lp.registry.model.personlocation import *
from canonical.launchpad.database.personnotification import *
from lp.registry.model.pillar import *
from lp.registry.model.product import *
from canonical.launchpad.database.productbounty import *
from canonical.launchpad.database.packaging import *
from lp.registry.model.productlicense import *
from lp.registry.model.productseries import *
from lp.registry.model.productrelease import *
from lp.registry.model.project import *
from canonical.launchpad.database.projectbounty import *
from lp.registry.model.poll import *
from lp.registry.model.announcement import *
from lp.answers.model.answercontact import *
from canonical.launchpad.database.bug import *
from canonical.launchpad.database.bugbranch import *
from canonical.launchpad.database.bugcve import *
from canonical.launchpad.database.bugwatch import *
from canonical.launchpad.database.bugsubscription import *
from canonical.launchpad.database.bugtarget import *
from canonical.launchpad.database.bugmessage import *
from canonical.launchpad.database.bugtask import *
from canonical.launchpad.database.bugactivity import *
from canonical.launchpad.database.bugattachment import *
from canonical.launchpad.database.bugnomination import *
from canonical.launchpad.database.bugnotification import *
from lp.registry.model.commercialsubscription import *
from canonical.launchpad.database.cve import *
from canonical.launchpad.database.cvereference import *
from canonical.launchpad.database.bugtracker import *
from canonical.launchpad.database.pofile import *
from canonical.launchpad.database.pofiletranslator import *
from canonical.launchpad.database.potemplate import *
from canonical.launchpad.database.potmsgset import *
from canonical.launchpad.database.pomsgid import *
from canonical.launchpad.database.potranslation import *
from canonical.launchpad.database.librarian import *
from canonical.launchpad.database.launchpadstatistic import *
from lp.registry.model.sourcepackage import *
from lp.registry.model.sourcepackagename import *
from lp.soyuz.model.sourcepackagerelease import *
from lp.soyuz.model.binarypackagerelease import *
from lp.soyuz.model.binarypackagename import *
from canonical.launchpad.database.binaryandsourcepackagename import *
from lp.soyuz.model.publishedpackage import *
from lp.registry.model.distribution import *
from canonical.launchpad.database.distributionbounty import *
from lp.registry.model.distributionmirror import *
from lp.registry.model.distributionsourcepackage import *
from lp.registry.model.distributionsourcepackagecache import *
from lp.soyuz.model.distributionsourcepackagerelease import *
from lp.registry.model.distroseries import *
from lp.soyuz.model.distroseriesbinarypackage import *
from canonical.launchpad.database.distroserieslanguage import *
from lp.soyuz.model.distroseriespackagecache import *
from lp.soyuz.model.distroseriessourcepackagerelease import *
from lp.soyuz.model.distroarchseries import *
from lp.soyuz.model.distroarchseriesbinarypackage import *
from lp.soyuz.model.distroarchseriesbinarypackagerelease\
    import *
from lp.registry.model.person import *
from canonical.launchpad.database.language import *
from canonical.launchpad.database.languagepack import *
from canonical.launchpad.database.translationgroup import *
from canonical.launchpad.database.translationimportqueue import *
from canonical.launchpad.database.translationmessage import *
from canonical.launchpad.database.translationsoverview import *
from canonical.launchpad.database.translationsperson import *
from canonical.launchpad.database.translationtemplateitem import *
from canonical.launchpad.database.translator import *
from lp.soyuz.model.processor import *
from lp.code.model.branch import *
from lp.code.model.branchmergeproposal import *
from lp.code.model.branchrevision import *
from lp.code.model.branchsubscription import *
from lp.code.model.branchvisibilitypolicy import *
from lp.soyuz.model.build import *
from lp.soyuz.model.builder import *
from lp.soyuz.model.buildqueue import *
from lp.soyuz.model.publishing import *
from lp.answers.model.faq import *
from lp.registry.model.featuredproject import *
from lp.soyuz.model.files import *
from canonical.launchpad.database.bounty import *
from canonical.launchpad.database.bountymessage import *
from canonical.launchpad.database.bountysubscription import *
from lp.registry.model.mentoringoffer import *
from canonical.launchpad.database.message import *
from lp.soyuz.model.queue import *
from canonical.launchpad.database.country import *
from canonical.launchpad.database.scriptactivity import *
from lp.blueprints.model.specification import *
from lp.blueprints.model.specificationbranch import *
from lp.blueprints.model.specificationbug import *
from lp.blueprints.model.specificationdependency import *
from lp.blueprints.model.specificationfeedback import *
from lp.blueprints.model.specificationsubscription import *
from canonical.launchpad.database.spokenin import *
from lp.blueprints.model.sprint import *
from lp.blueprints.model.sprintattendance import *
from lp.blueprints.model.sprintspecification import *
from canonical.launchpad.database.structuralsubscription import *
from canonical.launchpad.database.logintoken import *
from lp.registry.model.codeofconduct import *
from lp.soyuz.model.component import *
from lp.soyuz.model.section import *
from canonical.shipit.model.shipit import *
from canonical.launchpad.database.vpoexport import *
from canonical.launchpad.database.vpotexport import *
from lp.registry.model.karma import *
from lp.registry.model.teammembership import *
from canonical.launchpad.database.temporaryblobstorage import *
from lp.answers.model.question import *
from lp.coop.answersbugs.model import *
from lp.answers.model.questionmessage import *
from lp.answers.model.questionreopening import *
from lp.answers.model.questionsubscription import *
from canonical.launchpad.database.poexportrequest import *
from lp.code.model.revision import *
from lp.registry.model.gpgkey import *
from lp.soyuz.model.archive import *
from canonical.launchpad.database.emailaddress import *
from canonical.launchpad.database.oauth import *
from lp.registry.model.entitlement import *
from lp.registry.model.mailinglist import *
from canonical.launchpad.database.hwdb import *
from lp.soyuz.model.archivedependency import *
from lp.soyuz.model.packagediff import *
from lp.code.model.codereviewcomment import *
from lp.soyuz.model.archivepermission import *
from lp.soyuz.model.packageset import *
