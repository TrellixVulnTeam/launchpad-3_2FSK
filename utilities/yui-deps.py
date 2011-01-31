#!/usr/bin/python
#
# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Print the YUI modules we are using."""

yui_deps = [
    './lib/canonical/launchpad/icing/yui/yui/yui-base-min.js',
    './lib/canonical/launchpad/icing/yui/yui/yui-later-min.js',
    './lib/canonical/launchpad/icing/yui/yui/yui-log-min.js',
    './lib/canonical/launchpad/icing/yui/dom/dom-base-min.js',
    './lib/canonical/launchpad/icing/yui/dom/dom-screen-min.js',
    './lib/canonical/launchpad/icing/yui/dom/dom-style-ie-min.js',
    './lib/canonical/launchpad/icing/yui/dom/dom-style-min.js',
    './lib/canonical/launchpad/icing/yui/dom/dom-min.js',
    './lib/canonical/launchpad/icing/yui/dom/selector-css2-min.js',
    './lib/canonical/launchpad/icing/yui/dom/selector-css3-min.js',
    './lib/canonical/launchpad/icing/yui/dom/selector-native-min.js',
    './lib/canonical/launchpad/icing/yui/dom/selector-min.js',
    './lib/canonical/launchpad/icing/yui/dump/dump-min.js',
    './lib/canonical/launchpad/icing/yui/event-custom/event-custom-base-min.js',
    './lib/canonical/launchpad/icing/yui/event-custom/event-custom-complex-min.js',
    './lib/canonical/launchpad/icing/yui/event-custom/event-custom-min.js',
    './lib/canonical/launchpad/icing/yui/event-gestures/event-flick-min.js',
    './lib/canonical/launchpad/icing/yui/event-gestures/event-gestures-min.js',
    './lib/canonical/launchpad/icing/yui/event-gestures/event-move-min.js',
    './lib/canonical/launchpad/icing/yui/event-simulate/event-simulate-min.js',
    './lib/canonical/launchpad/icing/yui/event-valuechange/event-valuechange-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-base-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-delegate-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-focus-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-key-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-mouseenter-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-mousewheel-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-resize-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-synthetic-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-touch-min.js',
    './lib/canonical/launchpad/icing/yui/event/event-min.js',
    './lib/canonical/launchpad/icing/yui/oop/oop-min.js',
    './lib/canonical/launchpad/icing/yui/substitute/substitute-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-base-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-color-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-curve-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-easing-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-node-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-scroll-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-xy-min.js',
    './lib/canonical/launchpad/icing/yui/anim/anim-min.js',
    './lib/canonical/launchpad/icing/yui/async-queue/async-queue-min.js',
    './lib/canonical/launchpad/icing/yui/attribute/attribute-base-min.js',
    './lib/canonical/launchpad/icing/yui/attribute/attribute-complex-min.js',
    './lib/canonical/launchpad/icing/yui/attribute/attribute-min.js',
    './lib/canonical/launchpad/icing/yui/base/base-base-min.js',
    './lib/canonical/launchpad/icing/yui/base/base-build-min.js',
    './lib/canonical/launchpad/icing/yui/base/base-pluginhost-min.js',
    './lib/canonical/launchpad/icing/yui/base/base-min.js',
    './lib/canonical/launchpad/icing/yui/cache/cache-base-min.js',
    './lib/canonical/launchpad/icing/yui/cache/cache-offline-min.js',
    './lib/canonical/launchpad/icing/yui/cache/cache-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/cache/cache-min.js',
    './lib/canonical/launchpad/icing/yui/classnamemanager/classnamemanager-min.js',
    './lib/canonical/launchpad/icing/yui/collection/array-extras-min.js',
    './lib/canonical/launchpad/icing/yui/collection/array-invoke-min.js',
    './lib/canonical/launchpad/icing/yui/collection/arraylist-add-min.js',
    './lib/canonical/launchpad/icing/yui/collection/arraylist-filter-min.js',
    './lib/canonical/launchpad/icing/yui/collection/arraylist-min.js',
    './lib/canonical/launchpad/icing/yui/collection/collection-min.js',
    './lib/canonical/launchpad/icing/yui/compat/compat-min.js',
    './lib/canonical/launchpad/icing/yui/console/console-filters-min.js',
    './lib/canonical/launchpad/icing/yui/console/console-min.js',
    './lib/canonical/launchpad/icing/yui/console/lang/console.js',
    './lib/canonical/launchpad/icing/yui/console/lang/console_en.js',
    './lib/canonical/launchpad/icing/yui/console/lang/console_es.js',
    './lib/canonical/launchpad/icing/yui/cookie/cookie-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-array-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-base-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-json-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-text-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-xml-min.js',
    './lib/canonical/launchpad/icing/yui/dataschema/dataschema-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-arrayschema-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-cache-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-function-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-get-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-io-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-jsonschema-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-local-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-polling-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-textschema-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-xmlschema-min.js',
    './lib/canonical/launchpad/icing/yui/datasource/datasource-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-date-format-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-date-parse-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-date-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-number-format-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-number-parse-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-number-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-xml-format-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-xml-parse-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-xml-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/datatype-min.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ar-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ar.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ca-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ca.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_da-DK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_da.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_de-AT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_de-DE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_de.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_el-GR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_el.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-AU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-GB.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-IE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-NZ.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-PH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-SG.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_en.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-AR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-BO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-CL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-CO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-EC.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-MX.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-PE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-PY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-UY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es-VE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_es.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fi-FI.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fr-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fr-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fr-FR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_fr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_hi-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_hi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_id-ID.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_id.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_it-IT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_it.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ja-JP.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ja.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ko-KR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ko.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ms-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ms.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_nb-NO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_nb.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_nl-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_nl-NL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_nl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_pl-PL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_pl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_pt-BR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_pt.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ro-RO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ro.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ru-RU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_ru.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_sv-SE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_sv.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_th-TH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_th.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_tr-TR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_tr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_vi-VN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_vi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_zh-Hans-CN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_zh-Hans.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_zh-Hant-HK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_zh-Hant-TW.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date-format_zh-Hant.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ar-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ar.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ca-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ca.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_da-DK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_da.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_de-AT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_de-DE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_de.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_el-GR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_el.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-AU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-GB.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-IE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-NZ.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-PH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-SG.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_en.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-AR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-BO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-CL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-CO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-EC.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-MX.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-PE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-PY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-UY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es-VE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_es.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fi-FI.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fr-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fr-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fr-FR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_fr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_hi-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_hi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_id-ID.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_id.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_it-IT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_it.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ja-JP.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ja.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ko-KR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ko.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ms-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ms.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_nb-NO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_nb.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_nl-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_nl-NL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_nl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_pl-PL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_pl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_pt-BR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_pt.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ro-RO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ro.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ru-RU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_ru.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_sv-SE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_sv.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_th-TH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_th.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_tr-TR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_tr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_vi-VN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_vi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_zh-Hans-CN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_zh-Hans.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_zh-Hant-HK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_zh-Hant-TW.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype-date_zh-Hant.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ar-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ar.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ca-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ca.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_da-DK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_da.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_de-AT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_de-DE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_de.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_el-GR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_el.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-AU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-GB.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-IE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-JO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-NZ.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-PH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-SG.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_en.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-AR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-BO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-CL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-CO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-EC.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-ES.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-MX.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-PE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-PY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-US.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-UY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es-VE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_es.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fi-FI.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fr-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fr-CA.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fr-FR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_fr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_hi-IN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_hi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_id-ID.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_id.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_it-IT.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_it.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ja-JP.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ja.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ko-KR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ko.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ms-MY.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ms.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_nb-NO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_nb.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_nl-BE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_nl-NL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_nl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_pl-PL.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_pl.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_pt-BR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_pt.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ro-RO.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ro.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ru-RU.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_ru.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_sv-SE.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_sv.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_th-TH.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_th.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_tr-TR.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_tr.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_vi-VN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_vi.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_zh-Hans-CN.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_zh-Hans.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_zh-Hant-HK.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_zh-Hant-TW.js',
    './lib/canonical/launchpad/icing/yui/datatype/lang/datatype_zh-Hant.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-constrain-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-ddm-base-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-ddm-drop-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-ddm-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-delegate-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-drag-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-drop-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-drop-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-gestures-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-proxy-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-scroll-min.js',
    './lib/canonical/launchpad/icing/yui/dd/dd-min.js',
    './lib/canonical/launchpad/icing/yui/editor/createlink-base-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-base-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-bidi-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-lists-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-para-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-tab-min.js',
    './lib/canonical/launchpad/icing/yui/editor/editor-min.js',
    './lib/canonical/launchpad/icing/yui/editor/exec-command-min.js',
    './lib/canonical/launchpad/icing/yui/editor/frame-min.js',
    './lib/canonical/launchpad/icing/yui/editor/selection-min.js',
    './lib/canonical/launchpad/icing/yui/history-deprecated/history-deprecated-min.js',
    './lib/canonical/launchpad/icing/yui/history/history-base-min.js',
    './lib/canonical/launchpad/icing/yui/history/history-hash-ie-min.js',
    './lib/canonical/launchpad/icing/yui/history/history-hash-min.js',
    './lib/canonical/launchpad/icing/yui/history/history-html5-min.js',
    './lib/canonical/launchpad/icing/yui/history/history-min.js',
    './lib/canonical/launchpad/icing/yui/imageloader/imageloader-min.js',
    './lib/canonical/launchpad/icing/yui/intl/intl-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-base-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-form-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-queue-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-upload-iframe-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-xdr-min.js',
    './lib/canonical/launchpad/icing/yui/io/io-min.js',
    './lib/canonical/launchpad/icing/yui/json/json-parse-min.js',
    './lib/canonical/launchpad/icing/yui/json/json-stringify-min.js',
    './lib/canonical/launchpad/icing/yui/json/json-min.js',
    './lib/canonical/launchpad/icing/yui/jsonp/jsonp-url-min.js',
    './lib/canonical/launchpad/icing/yui/jsonp/jsonp-min.js',
    './lib/canonical/launchpad/icing/yui/loader/loader-base-min.js',
    './lib/canonical/launchpad/icing/yui/loader/loader-rollup-min.js',
    './lib/canonical/launchpad/icing/yui/loader/loader-yui3-min.js',
    './lib/canonical/launchpad/icing/yui/loader/loader-min.js',
    './lib/canonical/launchpad/icing/yui/node-flick/node-flick-min.js',
    './lib/canonical/launchpad/icing/yui/node-focusmanager/node-focusmanager-min.js',
    './lib/canonical/launchpad/icing/yui/node-menunav/node-menunav-min.js',
    './lib/canonical/launchpad/icing/yui/node/align-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-base-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-event-delegate-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-event-html5-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-event-simulate-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-pluginhost-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-screen-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-style-min.js',
    './lib/canonical/launchpad/icing/yui/node/node-min.js',
    './lib/canonical/launchpad/icing/yui/node/shim-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/overlay/overlay-min.js',
    './lib/canonical/launchpad/icing/yui/plugin/plugin-min.js',
    './lib/canonical/launchpad/icing/yui/pluginhost/pluginhost-min.js',
    './lib/canonical/launchpad/icing/yui/profiler/profiler-min.js',
    './lib/canonical/launchpad/icing/yui/querystring/querystring-parse-simple-min.js',
    './lib/canonical/launchpad/icing/yui/querystring/querystring-parse-min.js',
    './lib/canonical/launchpad/icing/yui/querystring/querystring-stringify-simple-min.js',
    './lib/canonical/launchpad/icing/yui/querystring/querystring-stringify-min.js',
    './lib/canonical/launchpad/icing/yui/querystring/querystring-min.js',
    './lib/canonical/launchpad/icing/yui/queue-promote/queue-promote-min.js',
    './lib/canonical/launchpad/icing/yui/scrollview/scrollview-base-min.js',
    './lib/canonical/launchpad/icing/yui/scrollview/scrollview-paginator-min.js',
    './lib/canonical/launchpad/icing/yui/scrollview/scrollview-scrollbars-min.js',
    './lib/canonical/launchpad/icing/yui/scrollview/scrollview-min.js',
    './lib/canonical/launchpad/icing/yui/slider/clickable-rail-min.js',
    './lib/canonical/launchpad/icing/yui/slider/range-slider-min.js',
    './lib/canonical/launchpad/icing/yui/slider/slider-base-min.js',
    './lib/canonical/launchpad/icing/yui/slider/slider-value-range-min.js',
    './lib/canonical/launchpad/icing/yui/slider/slider-min.js',
    './lib/canonical/launchpad/icing/yui/sortable/sortable-scroll-min.js',
    './lib/canonical/launchpad/icing/yui/sortable/sortable-min.js',
    './lib/canonical/launchpad/icing/yui/stylesheet/stylesheet-min.js',
    './lib/canonical/launchpad/icing/yui/swf/swf-min.js',
    './lib/canonical/launchpad/icing/yui/swfdetect/swfdetect-min.js',
    './lib/canonical/launchpad/icing/yui/tabview/tabview-base-min.js',
    './lib/canonical/launchpad/icing/yui/tabview/tabview-plugin-min.js',
    './lib/canonical/launchpad/icing/yui/tabview/tabview-min.js',
    './lib/canonical/launchpad/icing/yui/test/test-min.js',
    './lib/canonical/launchpad/icing/yui/transition/transition-native-min.js',
    './lib/canonical/launchpad/icing/yui/transition/transition-timer-min.js',
    './lib/canonical/launchpad/icing/yui/transition/transition-min.js',
    './lib/canonical/launchpad/icing/yui/uploader/uploader-min.js',
    './lib/canonical/launchpad/icing/yui/widget-anim/widget-anim-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-base-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-child-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-htmlparser-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-locale-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-parent-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-position-align-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-position-constrain-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-position-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-stack-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-stdmod-min.js',
    './lib/canonical/launchpad/icing/yui/widget/widget-min.js',
    './lib/canonical/launchpad/icing/yui/yql/yql-min.js',
    './lib/canonical/launchpad/icing/yui/yui/features-min.js',
    './lib/canonical/launchpad/icing/yui/yui/get-min.js',
    './lib/canonical/launchpad/icing/yui/yui/intl-base-min.js',
    './lib/canonical/launchpad/icing/yui/yui/rls-min.js',
    './lib/canonical/launchpad/icing/yui/yui/yui-throttle-min.js',
]

for line in yui_deps:
    print line
