// Some Javascript code from Plone Solutions
// http://www.plonesolutions.com, thanks!

function initHelpPanel() {
  /* 
    With CSS but no JavaScript, Launchpad is useful with the help always off,
    but not with the help always on, because it covers the page content.
    So the help panel is hidden by default. Then if JavaScript is available,
    this function hooks up the expand/collapse JavaScript to the panel, then
    reveals it in collapsed mode.
  */
  if (document.getElementById) {
    tab = document.getElementById('help-tab');
    helpwidget = document.getElementById('help');
    tab.onclick = function() {
      if (helpwidget.className == 'closed') {
        helpwidget.className = 'open'
      } else {
        helpwidget.className = 'closed'
      };
      return false;
    }
    helpwidget.style.visibility = 'visible';
  }
}

function initPortlets() {
  if (document.getElementById) {
    portlets = getElementsByTagAndClassName('div', 'portlet', 'portlets');
    /* The above line fails in Internet Explorer and I don't know why. */
    actionsMenu = document.getElementById('actions');
    for (var i=0; i<portlets.length; ++i) {
      var portlet = portlets[i];
      if (portlet.getAttribute('id') != 'actions') {
        portlet.className = 'portlet collapsed';
        headings = getElementsByTagAndClassName('h2', null, portlet);
        if (headings.length > 0) {
          heading = headings[0];
          heading.onclick = function() {
            /* This assumes the portlet is the parent element of its heading: */
            portletToToggle = this.parentNode;
            if (hasElementClass(portletToToggle, 'collapsed')) {
              removeElementClass(portletToToggle, 'collapsed');
              addElementClass(portletToToggle, 'expanded');
            } else {
              removeElementClass(portletToToggle, 'expanded');
              addElementClass(portletToToggle, 'collapsed');
            };
          }
          heading.style.cursor = 'pointer';
          heading.style.cursor = 'hand';
        }
      }
    }
  }
}

function registerLaunchpadFunction(func) {
    // registers a function to fire onload.
    // Use this for initilaizing any javascript that should fire once the page
    // has been loaded.
    connect(window, 'onload', func);
}

function sendWindowDims() {
    dims = getViewportDimensions();
    doSimpleXMLHttpRequest('/+dims', dims);
}
registerLaunchpadFunction(sendWindowDims);

function getContentArea() {
    // to end all doubt on where the content sits. It also felt a bit
    // silly doing this over and over in every function, even if it is
    // a tiny operation. Just guarding against someone changing the
    // names again, in the name of semantics or something.... ;)
    var node = document.getElementById('maincontent');
    if (!node) {
        node = document.getElementById('content');
    }
    return node;
}

function activateCollapsibles() {
    // a script that searches for sections that can be (or are
    // already) collapsed - and enables the collapse-behavior

    // usage : give the class "collapsible" to a fieldset also, give
    // it a <legend> with some descriptive text.  you can also add the
    // class "collapsed" amounting to a total of
    // <fieldset class="collapsible collapsed"> to make the section
    // pre-collapsed

    // terminate if we hit a non-compliant DOM implementation
    if (!document.getElementsByTagName)
        return false;
    if (!document.getElementById)
        return false;

    // only search in the content-area
    var contentarea = getContentArea();
    if (!contentarea)
        return false;

    // gather all objects that are to be collapsed
    // we only do fieldsets for now. perhaps DIVs later...
    var collapsibles = contentarea.getElementsByTagName('fieldset');

    for (var i = 0; i < collapsibles.length; i++) {
        if (collapsibles[i].className.indexOf('collapsible') == -1)
            continue;

        var legends = collapsibles[i].getElementsByTagName('LEGEND');

        // get the legend
        // if there is no legend, we do not touch the fieldset at all.
        // we assume that if there is a legend, there is only
        // one. nothing else makes any sense
        if (!legends.length)
            continue;
        var legend = legends[0];

        //create an anchor to handle click-events
        var anchor = document.createElement('a');
        anchor.href = '#';
        anchor.onclick = toggleCollapsible;

        // add the icon/button with its functionality to the legend
        var icon = document.createElement('img');
        icon.setAttribute('src','/@@/treeExpanded');
        icon.setAttribute('class','collapseIcon');
        icon.setAttribute('height','16');
        icon.setAttribute('width','16');

        // insert the icon icon at the start of the anchor
        anchor.appendChild(icon);

        // reparent all the legend's children into a span, and the span
        // into an anchor. The span is used to underline the legend
        // text; because the img is inside the anchor, we can't
        // underline the whole anchor.
        var span = document.createElement('span');
        while (legend.hasChildNodes()) {
            var child = legend.firstChild;
            legend.removeChild(child);
            span.appendChild(child);
        }
        anchor.appendChild(span);

        // add the anchor to the legend
        legend.appendChild(anchor);

        // wrap the contents inside a div to make turning them on and
        // off simpler.  unless something very strange happens, this
        // new div should always be the last childnode we'll give it a
        // class to make sure.

        var hiderWrapper = document.createElement('div');
        hiderWrapper.setAttribute('class','collapseWrapper');

        // also add a new div describing that the element is collapsed.
        var collapsedDescription = document.createElement('div');
        collapsedDescription.setAttribute('class','collapsedText');
        collapsedDescription.style.display = 'none';

        // if the fieldset has the class of "collapsed", pre-collapse
        // it. This can be used to preserve valuable UI-space
        if (collapsibles[i].className.indexOf('collapsed') != -1 ) {
            icon.setAttribute('src','/@@/treeCollapsed');
            collapsedDescription.style.display = 'block';
            setElementClass(hiderWrapper, 'collapsed');
            // Remove "collapsed" from the fieldset to neuter the main CSS:
            removeElementClass(collapsibles[i], 'collapsed');
        }

        // now we have the wrapper div.. Stuff all the contents inside it
        var nl = collapsibles[i].childNodes.length;
        for (var j = 0; j < nl; j++){
            var node = collapsibles[i].childNodes[0];
            if (node.nodeName == 'LEGEND') {
                if (collapsibles[i].childNodes.length > 1) {
                    hiderWrapper.appendChild(collapsibles[i].childNodes[1]);
                }
            } else {
                hiderWrapper.appendChild(collapsibles[i].childNodes[0]);
            }
        }
        // and add it to the document
        collapsibles[i].appendChild(hiderWrapper);
        collapsibles[i].insertBefore(collapsedDescription, hiderWrapper);
    }
}
registerLaunchpadFunction(activateCollapsibles);

function toggleCollapsible(e) {
    // this is the function that collapses/expands fieldsets. 

    // "this" is the node that the event is attached to
    var node = this;

    // walk up the node hierarchy until we find the <legend> element
    while (node.nodeName.toLowerCase() != 'legend') {
        node = node.parentNode;
        if (!node)
            return false;
    }

    // the expander image is legend -> a -> img
    var icon = node.firstChild.firstChild;
    var legend = node;

    if (icon.getAttribute('src').indexOf(
                '/@@/treeCollapsed') != -1) {
        // that was an ugly check, but IE rewrites image sources to
        // absolute urls from some sick reason....
        icon.setAttribute('src','/@@/treeExpanded');
        swapElementClass(legend.parentNode.lastChild, 'collapsed', 'expanded');
        swapElementClass(
            legend.parentNode.childNodes[1], 'expanded', 'collapsed');
    } else {
        icon.setAttribute('src','/@@/treeCollapsed');
        swapElementClass(legend.parentNode.lastChild, 'expanded', 'collapsed');
        swapElementClass(
            legend.parentNode.childNodes[1], 'collapsed', 'expanded');
    }

    return false;
}

function activateFoldables() {
    // Create links to toggle the display of foldable content.
    var elements = MochiKit.DOM.getElementsByTagAndClassName('*', 'foldable');
    for (var i = 0; i < elements.length; i++) {
        var ellipsis = document.createElement('a');
        ellipsis.style.textDecoration = 'underline';
        ellipsis.href = 'javascript:void(0)';
        ellipsis.onclick = toggleFoldable;
        ellipsis.appendChild(document.createTextNode('[...]'));
        
        var span = elements[i];
        span.parentNode.insertBefore(ellipsis, span);
        span.insertBefore(document.createElement('br'), span.firstChild);
        span.style.display = 'none';
    }
}
registerLaunchpadFunction(activateFoldables);

function toggleFoldable(e) {
    // Collapse/expand a folded passage of text or a signature. 
    var node = this;
    while (node = node.nextSibling) {
        if (node.nodeType != 1 && node.className.indexOf('foldable') == -1) {
            // node is not an ELEMENT_NODE of foldable class
            continue;
        }
        if (node.style.display == 'none') {
            node.style.display = 'inline';
        } else {
            node.style.display = 'none';
        }
    }
}

// Add/remove items between selection lists by double clicking:
function addSelectedKeywords(fromlist,tolist) {
    var predefSubjects = document.getElementById(fromlist);
    for (var x = 0; x < predefSubjects.length; x++) {
        if (predefSubjects[x].selected) {
            addNewKeyword(tolist, predefSubjects[x].text);
        }
    }
}

function addNewKeyword(tolist, newWord) {
    var selSubjects = document.getElementById(tolist);
    for (var x = 0; x < selSubjects.length; x++) {
        if (selSubjects[x].text == newWord) {
            return false;
        }
    }
    var ssl = selSubjects.length;
    selSubjects[ssl] = new Option(newWord);
}

function selectAllWords() {
    var keyword = document.getElementsByTagName('select');

    for (var i = 0; i < keyword.length; i++) {
        if (keyword[i].multiple) {
            for (var x = 0; x < keyword[i].options.length; x++) {
                keyword[i].options[x].selected = true;
            }
        }
    }
}

function removeWords(thelist) {
    var selSubjects = document.getElementById(thelist);

    for (var x = selSubjects.length-1; x >= 0 ; x--) {
        if (selSubjects[x].selected) {
            selSubjects[x] = null;
        }
    }
}

// XXXX: 20060809 jamesh
// The setFocus() function should be removed once we've migrated away
// from GeneralForm.

// Focus on error or tabindex=1 
function setFocus() {
    var xre = new RegExp(/\berror\b/);
    var formnodes, formnode, divnodes, node, inputnodes, inputnode;

    // Search only forms to avoid spending time on regular text
    formnodes = document.getElementsByTagName('form');
    for (var f = 0; (formnode = formnodes.item(f)); f++) {
        // Search for errors first, focus on first error if found
        divnodes = formnode.getElementsByTagName('div');
        for (var i = 0; (node = divnodes.item(i)); i++) {
            if (xre.exec(node.className)) {
                inputnode = node.getElementsByTagName('input').item(0);
                if (inputnode) {
                    inputnode.focus();
                    return;   
                }
            }
        }

        // If no error, focus on input element with tabindex 1
        var inputnodes = formnode.getElementsByTagName('input');
        for (var i = 0; (node = inputnodes.item(i)); i++) {
           if (node.getAttribute('tabindex') == 1) {
               node.focus();
               return;
           }
        }
    }
}
registerLaunchpadFunction(setFocus);

function setFocusByName(name) {
    // Focus the first element matching the given name which can be focused.
    var nodes = document.getElementsByName(name);
    for (var i = 0; i < nodes.length; i++) {
        var node = nodes[i];
        if (node.focus) {
            node.focus();
            break;
        }
    }
}

function popup_window(url, name, width, height) {
    var iframe = document.getElementById('popup_iframe_' + name);
    if (!iframe.src) {
        // The first time this handler runs the window may not have been
        // set up yet; sort that out.
        iframe.style.width = width + 'px';
        iframe.style.height = height + 'px';
        iframe.style.position = 'absolute';
        iframe.style.background = 'white';
        iframe.src = url
    }
    iframe.style.display = 'inline';
    // I haven't found a way of making the search form focus again when
    // the popup window is redisplayed. I tried doing an
    //    iframe.contentDocument.searchform.search.focus()
    // but nothing happens.. -- kiko, 2007-03-12
}

// from richard braine for the source import forms
function morf(x) {
    // morf morphs form. it takes a radio choice as argument
    // and shows and hides given divs as a result
    function showdiv() {
        for(var i = 0; i < arguments.length; i++) {
            //document.all[arguments[i]].style.visibility='visible';
            document.getElementById(arguments[i]).style.visibility='visible';
        }
    }
    function hidediv(){
        for(var i = 0; i < arguments.length; i++) {
            //document.all[arguments[i]].style.visibility='hidden';
            document.getElementById(arguments[i]).style.visibility='hidden';
        }
    }
    switch(true){
    case x=='cvs':
        showdiv('cvsdetails');
        hidediv('svndetails');
        break;
    case x=='svn':
        showdiv('svndetails');
        hidediv('cvsdetails');
        break;
    // case x=='arch':
    //     showdiv('archdetails');
    //     hidediv('cvsdetails', 'svndetails');
    //     break;
    }
}

function selectWidget(widget_name, event) {
  if (event && (event.keyCode == 9 || event.keyCode == 13))
      // Avoid firing if user is tabbing through or simply pressing
      // enter to submit the form.
      return;
  document.getElementById(widget_name).checked = true;
}

// Set the disabled attribute of the widgets with the given ids.
function setDisabled(disabled /* widget_ids ... */) {
    for (var i=1; i<arguments.length; i++) {
        var widget = document.getElementById(arguments[i])
        widget.disabled = disabled
    }
}

function convertTextInputToTextArea(text_input_id, rows) {
    var current_text_input = getElement(text_input_id);
    var new_text_area = document.createElement("textarea");
    var attributes = {
        'id': text_input_id,
        'rows': rows,
        'name': getNodeAttribute(current_text_input, 'name'),
        'lang': getNodeAttribute(current_text_input, 'lang'),
        'dir': getNodeAttribute(current_text_input, 'dir')
    };

    updateNodeAttributes(new_text_area, attributes);

    // we set the javascript events because updateNodeAttributes gets confused
    // with those events, because it says that 'event' is not defined. 'event'
    // is one of the arguments of the javascript call that is being copied.
    new_text_area.setAttribute('onKeyPress', getNodeAttribute(current_text_input, 'onkeypress'));
    new_text_area.setAttribute('onChange', getNodeAttribute(current_text_input, 'onchange'));
    new_text_area.value = current_text_input.value;
    swapDOM(current_text_input, new_text_area);

}

function upgradeToTextAreaForTranslation(text_input_id) {
    var rows = 6;

    current_text_input = getElement(text_input_id);
    current_text_input.parentNode.removeChild(
        getElement(text_input_id + '_to_textarea'));
    convertTextInputToTextArea(text_input_id, rows);
}

function unescapeHTML(unescaped_string) {
    // Based on prototype's unescapeHTML method.
    // See launchpad bug #78788 for details.
    var div = document.createElement('div');
    div.innerHTML = unescaped_string;
    return div.childNodes[0] ? div.childNodes[0].nodeValue : '';
}

function copyInnerHTMLById(from_id, to_id) {
    var from = getElement(from_id);
    var to = getElement(to_id);

    // The replacement regex strips all tags from the html.
    to.value = unescapeHTML(from.innerHTML.replace(/<\/?[^>]+>/gi, ""));

}

function writeTextIntoPluralTranslationFields(
    from_id, to_id_pattern, nplurals) {
    // skip when x is 0, as that is the singular
    for (var x = 1; x < nplurals; x++) {
        to_id = to_id_pattern + x + "_new";
        copyInnerHTMLById(from_id, to_id);
    }
}
