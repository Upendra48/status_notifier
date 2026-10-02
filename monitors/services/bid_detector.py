from collections.abc import Iterable

from lxml.html import HtmlElement


_STRUCTURAL_TAGS = {
	'table',
	'tbody',
	'thead',
	'tfoot',
	'tr',
	'ul',
	'ol',
}
_INLINE_TAGS = {
	'a',
	'b',
	'em',
	'i',
	'label',
	'small',
	'span',
	'strong',
}
_HEADING_TAGS = {f'h{level}' for level in range(1, 7)}


def find_entries(container: HtmlElement, bid_selector: str | None) -> list[HtmlElement]:
	if bid_selector and bid_selector.strip():
		if bid_selector.startswith('/'):
			matches = container.xpath(bid_selector)
		else:
			matches = container.cssselect(bid_selector)
		return _entry_elements(matches)

	for selector in ('tbody tr', 'li'):
		entries = _entry_elements(container.cssselect(selector))
		if entries:
			return entries

	direct_children = container.xpath('./*')
	return _entry_elements(
		child
		for child in direct_children
		if child.tag.lower() not in _STRUCTURAL_TAGS | _INLINE_TAGS | _HEADING_TAGS
	)


def _entry_elements(matches: Iterable[object]) -> list[HtmlElement]:
	entries = []
	for match in matches:
		if not isinstance(match, HtmlElement):
			continue
		text = ''.join(match.itertext()).strip()
		class_names = match.get('class', '').lower().split()
		is_header = (
			match.tag.lower() in _HEADING_TAGS | {'header', 'th'}
			or any('header' in class_name for class_name in class_names)
			or bool(match.xpath('.//th'))
		)
		if text and not is_header:
			entries.append(match)
	return entries