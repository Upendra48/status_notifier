from cssselect import SelectorError
from lxml import etree, html
from lxml.html import HtmlElement


def find_container(
	html_content: str,
	selector: str | None,
) -> tuple[HtmlElement | None, str | None]:
	if not selector or not selector.strip():
		return None, 'missing_selector'

	document = html.fromstring(html_content)
	if selector.startswith('/') or selector.startswith('//'):
		try:
			matches = document.xpath(selector)
		except etree.XPathError as exc:
			return None, f'invalid_xpath_selector: {exc}'
	else:
		try:
			matches = document.cssselect(selector)
		except (SelectorError, etree.XPathError) as exc:
			return None, f'invalid_css_selector: {exc}'

	for match in matches:
		if isinstance(match, HtmlElement):
			return match, None
	return None, 'container_not_found'