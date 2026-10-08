from monitors.models import BidStatus


def get_report_category(status: str, spider_broken: bool) -> str:
	if spider_broken and status == BidStatus.ACTIVE:
		return 'active'
	if spider_broken and status in {BidStatus.UNKNOWN, BidStatus.ERROR}:
		return 'review'
	if status == BidStatus.NO_BID:
		return 'no_bid'
	return 'logged'
