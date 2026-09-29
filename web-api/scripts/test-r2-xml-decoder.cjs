'use strict';

const assert = require('node:assert/strict');
const { decodeXml, escapeXml } = require('../src/lib/r2-xml.js');

assert.equal(decodeXml('&amp;&lt;&gt;&quot;&#39;'), '&<>"\'');
assert.equal(decodeXml('&amp;lt;'), '&lt;', 'decoder must not recursively turn &amp;lt; into <');
assert.equal(decodeXml('&amp;amp;'), '&amp;', 'decoder must decode one XML layer only');

const raw = 'a&<>"\'';
assert.equal(decodeXml(escapeXml(raw)), raw);
console.log('PASS R2 XML decoder performs exactly one decode pass');
