"""Pure first-date title rules, pinned from Close field updater 46427f98fc8a.

Used only to identify the meeting behind an existing First Sales Call Booked
Date. Counting, outcomes, cancellations, funnels, and dates remain dashboard rules.
"""
import re
from first_call_roster import SCRAPER_TITLE_MAP

EXCLUDED_OWNERS = {'user_5cZRqXu8kb4O1IeBVA98UMcMEhYZUhx1fnCHfSL0YMV', 'user_yRF070m26JE67J6CJqzkAB3IqY7btNm1K5RisCglKa6'}
SETTER_OWNERS = {'user_EmhqCmaHERTfgfWnPADiLGEqQw3ENvRYd3u1VEmblIp', 'user_4sfuKGMbv0LQZ4hpS8ipASv406kKTSNP5Xx79jOwSqM'}
RE_CANCELED = re.compile('^canceled[\\s:]?', re.IGNORECASE)
RE_FOLLOWUP = re.compile('follow[\\-\\s]?up|fallow\\s+up|f/u\\b|next\\s+steps|reschedul', re.IGNORECASE)
RE_ENROLLMENT = re.compile('enrollment|silver\\s+start\\s*up|bronze\\s+enrollment|questions\\s+on\\s+enrollment', re.IGNORECASE)
RE_DISCOVERY_TITLE = re.compile('vending\\s+quick\\s+discovery', re.IGNORECASE)
RE_POSTWEBINAR_TITLE = re.compile('post\\s+masterclass\\s+strategy\\s+call', re.IGNORECASE)
RE_ROUTE_PLANNING_TITLE = re.compile('route\\s+planning\\s+call', re.IGNORECASE)
RE_REACT_EMAIL_TITLE = re.compile('vending\\s+consultation\\s+&\\s+strategy\\s+session', re.IGNORECASE)
RE_QUICK_DISC_TITLE = re.compile('vending\\s+consult\\s+call', re.IGNORECASE)
RE_VENDHUB_CONSULTATION = re.compile('vendhub\\s+consultation\\s+call', re.IGNORECASE)
RE_VENDHUB_NEXTSTEPS = re.compile('vendhub\\s+next\\s+steps\\s+call', re.IGNORECASE)
RE_VENDHUB_ANY = re.compile('vend[\\s-]?hub', re.IGNORECASE)

CLOSER_PATTERNS = [re.compile('vending\\s+strategy\\s+call', re.IGNORECASE), re.compile('vendingpren[eu]+rs?\\s+consultation', re.IGNORECASE), re.compile('vendingpren[eu]+rs?\\s+strategy\\s+call', re.IGNORECASE), re.compile('new\\s+vendingpren[eu]+r\\s+strategy\\s+call', re.IGNORECASE), re.compile('vending\\s+consult\\b', re.IGNORECASE), re.compile('post\\s+masterclass\\s+strategy\\s+call', re.IGNORECASE), re.compile('vending\\s+route\\s+consultation', re.IGNORECASE), re.compile('cash[\\-\\s]flowing\\s+vending\\s+route\\s+advisory\\s+interview', re.IGNORECASE), re.compile('vending\\s+route\\s+advisory\\s+call', re.IGNORECASE), re.compile('vending\\s+route\\s+discovery', re.IGNORECASE), re.compile('vending\\s+consultation\\s+&\\s+strategy\\s+session', re.IGNORECASE)]

def _is_hard_excluded(meeting: dict) -> bool:
    """Returns True if this meeting should be ignored entirely regardless of type."""
    user_id = meeting.get('user_id') or ''
    if user_id in EXCLUDED_OWNERS:
        return True
    title = (meeting.get('title') or '').strip()
    if RE_CANCELED.match(title):
        return True
    if RE_FOLLOWUP.search(title):
        return True
    if re.search('\\banthony\\b', title, re.IGNORECASE) and re.search('\\bq&a\\b', title, re.IGNORECASE):
        return True
    if RE_ENROLLMENT.search(title):
        return True
    return False

def classify_meeting(meeting: dict) -> tuple:
    """
    Returns (tier, setter_name) where tier is one of:
      "closer"              — qualifying first sales/closer meeting
      "setter"              — discovery/setter meeting (not a closer call)
      "post_webinar"        — Post Masterclass Strategy Call (closer + post-webinar flag)
      "scraper"             — scraper meeting title (closer + scraper + setter name)
      "vendhub_consultation"— Vendhub Consultation Call (closer + VendHub = Standard Booking)
      "vendhub_nextsteps"   — Vendhub Next Steps Call (closer + VendHub = VendHub Q&A Booking)
      "react_email"         — Vending Consultation & Strategy Session (closer + Funnel Name = Reactivation Email)
      None                  — irrelevant, ignore

    setter_name is only populated for "scraper" tier.

    NOTE: Scraper titles are checked BEFORE hard excludes — they all contain
    "Next Steps" which would otherwise be caught by the followup hard exclude.
    SCRAPER_TITLE_MAP order matters: most specific (longest) pattern first.
    """
    user_id = meeting.get('user_id') or ''
    title = (meeting.get('title') or '').strip()
    for scraper in SCRAPER_TITLE_MAP:
        pattern = scraper['pattern']
        setter_name = scraper['rep']
        if pattern.search(title):
            if user_id not in EXCLUDED_OWNERS:
                return ('scraper', setter_name)
    if RE_VENDHUB_NEXTSTEPS.search(title):
        if user_id not in EXCLUDED_OWNERS:
            return ('vendhub_nextsteps', None)
    if RE_VENDHUB_CONSULTATION.search(title):
        if user_id not in EXCLUDED_OWNERS:
            return ('vendhub_consultation', None)
    if _is_hard_excluded(meeting):
        return (None, None)
    if user_id in SETTER_OWNERS:
        return ('setter', None)
    if RE_DISCOVERY_TITLE.search(title):
        return ('setter', None)
    if RE_POSTWEBINAR_TITLE.search(title):
        return ('post_webinar', None)
    if RE_ROUTE_PLANNING_TITLE.search(title):
        return ('route_planning', None)
    if RE_REACT_EMAIL_TITLE.search(title):
        return ('react_email', None)
    if RE_QUICK_DISC_TITLE.search(title):
        return ('quick_discovery', None)
    for pattern in CLOSER_PATTERNS:
        if pattern.search(title):
            return ('closer', None)
    return (None, None)
    if user_id in SETTER_OWNERS:
        return 'setter'
    if RE_DISCOVERY_TITLE.search(title):
        return 'setter'
    if RE_POSTWEBINAR_TITLE.search(title):
        return 'post_webinar'
    for pattern in CLOSER_PATTERNS:
        if pattern.search(title):
            return 'closer'
    return None
