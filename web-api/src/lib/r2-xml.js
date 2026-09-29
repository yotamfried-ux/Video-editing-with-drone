'use strict';

const XML_DECODE = Object.freeze({
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
});

function decodeXml(value) {
  return value.replace(/&(?:amp|lt|gt|quot|#39);/g, (entity) => XML_DECODE[entity] ?? entity);
}

function escapeXml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

module.exports = { decodeXml, escapeXml };
