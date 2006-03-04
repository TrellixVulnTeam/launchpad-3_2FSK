# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Rejection and acceptance message templates for the uploader etc."""

__all__ = [
    'rejection_template',
    'new_template',
    'accepted_template',
    'announce_template'
    ]

rejection_template = """From: %(SENDER)s
To: %(RECIPIENT)s
Precedence: bulk
Subject: %(CHANGES)s Rejected

Rejected:
%(SUMMARY)s

%(CHANGESFILE)s

===

If you don't understand why your files were rejected, or if the
override file requires editing, reply to this email.
"""

new_template = """From: %(SENDER)s
To: %(RECIPIENT)s
Precedence: bulk
Subject: %(CHANGES)s is NEW

%(SUMMARY)s

%(CHANGESFILE)s

Your package contains new components which requires manual editing of
the override file.  It is ok otherwise, so please be patient.  New
packages are usually added to the overrides about once a week.

You may have gotten the distrorelease wrong.  If so, you may get warnings
above if files already exist in other distroreleases.
"""

accepted_template="""From: %(SENDER)s
To: %(RECIPIENT)s
Precedence: bulk
Subject: Accepted %(SOURCE)s %(VERSION)s (%(ARCH)s)

Accepted:
%(SUMMARY)s

%(CHANGESFILE)s

==

Announcing to %(ANNOUNCE)s

Thank you for your contribution to %(DISTRO)s.
"""

announce_template="""From: %(MAINTAINERFROM)s
To: %(ANNOUNCE)s
Subject: Accepted %(SOURCE)s %(VERSION)s (%(ARCH)s)

Accepted:
%(SUMMARY)s

%(CHANGESFILE)s

"""
