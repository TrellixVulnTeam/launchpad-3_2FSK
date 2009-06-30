#! /usr/bin/python2.4
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=W0403

__metaclass__ = type

import _pythonpath

# This script merges POTMsgSets for sharing POTemplates.  This involves
# deleting records that we'd never delete otherwise.  So before running,
# make sure rosettaadmin has the privileges to delete POTMsgSets and
# TranslationTemplateItems:
#
# GRANT DELETE ON POTMsgSET TO rosettaadmin;
# GRANT DELETE ON  TranslationTemplateItem TO rosettaadmin; 

from canonical.launchpad.scripts.message_sharing_migration import (
    MessageSharingMerge)


if __name__ == '__main__':
    script = MessageSharingMerge(
        'canonical.launchpad.scripts.message-sharing-merge',
        dbuser='rosettaadmin')
    script.run()
