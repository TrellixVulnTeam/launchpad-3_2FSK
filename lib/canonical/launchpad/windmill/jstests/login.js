/* 
Copyright 2008 Canonical Ltd.  All rights reserved.

Namespaces for tests requiring to be logged in.
*/

/* Logged in as Foo Bar. */
var test_logged_in_as_foo_bar = {};
test_logged_in_as_foo_bar.setup = [
    {"params": {"link": "Log in \/ Register"}, 
        "method": "asserts.assertNode"},
    {"params": {"link": "Log in \/ Register"}, "method": "click"},
    {"params": {"timeout": "8000", "id": "email"}, 
        "method": "waits.forElement"},
    {"params": {"text": "foo.bar@canonical.com", "id": "email"}, 
        "method": "type"},
    {"params": {"text": "test", "id": "password"}, "method": "type"},
    {"params": {"name": "loginpage_submit_login"}, "method": "click"},
    {"params": {"link": "Foo Bar"}, "method": "waits.forElement"}
    ];

test_logged_in_as_foo_bar.teardown = [
    {"params": {"name": "logout"}, "method": "click"},
    // We need the waits.forPageLoad here because it's likely that the
    // xpath expression might match on the previous page.
    {"params": {}, "method": "waits.forPageLoad"},
    {"params": {"xpath": "\/html\/body[@id='document']\/div[@id='mainarea']\/div[@id='container']\/div"}, "method": "waits.forElement"},
    {"params": {"xpath": "\/html\/body[@id='document']\/div[@id='mainarea']\/div[@id='container']\/div", "validator": "You have been logged out"}, "method": "asserts.assertText"}
    ];
