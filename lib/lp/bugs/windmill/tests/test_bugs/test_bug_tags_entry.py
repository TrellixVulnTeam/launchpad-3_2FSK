# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for the bug tag entry UI."""

__metaclass__ = type
__all__ = []

from windmill.authoring import WindmillTestClient

from canonical.launchpad.windmill.testing import lpuser

def test_bug_tags_entry():
    """Test bug tags inline, auto-completing UI."""
    client = WindmillTestClient('Bug tags entry test')

    # First, we add some official tags to test with

    lpuser.FOO_BAR.ensure_login(client)

    client.open(url='http://bugs.launchpad.dev:8085/firefox')
    client.waits.forPageLoad(timeout=u'100000')
    client.waits.sleep(milliseconds=u'8000')

    client.click(link=u'Edit official tags')
    client.waits.forPageLoad(timeout=u'100000')
    client.waits.sleep(milliseconds=u'8000')

    client.type(text=u'eenie', id=u'new-tag-text')
    client.click(id=u'new-tag-add')
    client.type(text=u'meenie', id=u'new-tag-text')
    client.click(id=u'new-tag-add')
    client.type(text=u'meinie', id=u'new-tag-text')
    client.click(id=u'new-tag-add')
    client.type(text=u'moe', id=u'new-tag-text')
    client.click(id=u'new-tag-add')
    # if the tags already exist the save button might be disabled.
    # make sure it's enabled so that we can complete the test.
    client.asserts.assertJS(js=u"""(function(){
            document.getElementById('save-button').disabled = false;
            return true;
        }());
    """)
    client.click(id=u'save-button')
    client.waits.forPageLoad(timeout=u'100000')
    client.asserts.assertJS(
        js=u'window.location == "http://bugs.launchpad.dev:8085/firefox"')

    # Now let's tag a bug using the auto-complete widget

    client.open(url='http://bugs.launchpad.dev:8085/firefox/+bug/5')
    client.waits.forPageLoad(timeout=u'300000')
    client.waits.sleep(milliseconds=u'8000')

    # XXX intellectronica 2009-05-26:
    # We (almost) consistently get an error on the following line
    # where instead of trigerring the onclick event handler we navigate
    # to the link's URL.

    client.click(id=u'edit-tags-trigger')
    client.waits.forElement(id=u'tag-input', timeout=u'8000')
    client.type(text=u'ee', id=u'tag-input')
    client.waits.sleep(milliseconds=u'1000')
    client.asserts.assertNode(classname=u'yui-autocomplete-list')
    client.click(id=u'item0')
    client.click(id=u'edit-tags-ok')
    client.waits.sleep(milliseconds=u'8000')
    client.asserts.assertText(id=u'tag-list', validator=u'eenie')

    # Test that anonymous users are prompted to log in.

    lpuser.ANONYMOUS.ensure_login(client)
    client.open(url='http://bugs.launchpad.dev:8085/firefox/+bug/5')
    client.waits.forPageLoad(timeout=u'50000')
    client.waits.sleep(milliseconds=u'8000')
    client.click(id=u'edit-tags-trigger')
    client.waits.forPageLoad(timeout=u'50000')
    client.asserts.assertJS(
        js=u'window.location == "http://bugs.launchpad.dev:8085/firefox/+bug/5/+edit/+login"')

