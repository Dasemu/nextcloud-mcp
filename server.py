import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, unquote, urljoin

import httpx
import vobject
from mcp.server.mcpserver import MCPServer
from vobject.icalendar import utc as ICAL_UTC

NC_HOST = os.environ["NEXTCLOUD_HOST"].rstrip("/")
NC_USER = os.environ["NEXTCLOUD_USERNAME"]
NC_PASS = os.environ["NEXTCLOUD_PASSWORD"]
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("BIND_PORT", "8082"))

DAV_ROOT = f"{NC_HOST}/remote.php/dav/files/{quote(NC_USER)}/"
CALDAV_ROOT = f"{NC_HOST}/remote.php/dav/calendars/{quote(NC_USER)}/"
CARDDAV_ROOT = f"{NC_HOST}/remote.php/dav/addressbooks/users/{quote(NC_USER)}/"
SPREED_API = f"{NC_HOST}/ocs/v2.php/apps/spreed/api/v1"
SPREED_API_V4 = f"{NC_HOST}/ocs/v2.php/apps/spreed/api/v4"
OCS_HEADERS = {"OCS-APIRequest": "true", "Accept": "application/json"}
DAV_NS = "{DAV:}"
CALDAV_NS = "{urn:ietf:params:xml:ns:caldav}"
CARDDAV_NS = "{urn:ietf:params:xml:ns:carddav}"

mcp = MCPServer("nextcloud")


def _client() -> httpx.Client:
    return httpx.Client(auth=(NC_USER, NC_PASS), timeout=30.0)


def _dav_url(path: str) -> str:
    path = path.strip("/")
    return urljoin(DAV_ROOT, quote(path))


def _parse_propfind(xml_text: str, base_path: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    entries = []
    for resp in root.findall(f"{DAV_NS}response"):
        href = resp.findtext(f"{DAV_NS}href") or ""
        propstat = resp.find(f"{DAV_NS}propstat")
        if propstat is None:
            continue
        prop = propstat.find(f"{DAV_NS}prop")
        is_dir = prop.find(f"{DAV_NS}resourcetype/{DAV_NS}collection") is not None
        size = prop.findtext(f"{DAV_NS}getcontentlength")
        mtime = prop.findtext(f"{DAV_NS}getlastmodified")
        name = unquote(href.rstrip("/").split("/")[-1])
        rel = unquote(href.split(f"/dav/files/{quote(NC_USER)}/", 1)[-1])
        if rel.strip("/") == base_path.strip("/"):
            continue
        entries.append({
            "name": name,
            "path": "/" + rel.strip("/"),
            "is_dir": is_dir,
            "size": int(size) if size else None,
            "modified": mtime,
        })
    return entries


def _parse_dt(value: str) -> datetime:
    text = value.strip()
    if "T" not in text:
        text += "T00:00:00"
    text = text.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ICAL_UTC)
    return dt


def _fmt_dt(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _set_field(component, name: str, value) -> None:
    if hasattr(component, name):
        getattr(component, name).value = value
    else:
        component.add(name).value = value


def _list_collections(root_url: str, resource_tag: str) -> list[dict]:
    body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:displayname/><d:resourcetype/></d:prop>
</d:propfind>"""
    with _client() as c:
        r = c.request("PROPFIND", root_url, content=body,
                       headers={"Depth": "1", "Content-Type": "application/xml"})
        r.raise_for_status()
    root = ET.fromstring(r.text)
    results = []
    for resp in root.findall(f"{DAV_NS}response"):
        href = resp.findtext(f"{DAV_NS}href") or ""
        propstat = resp.find(f"{DAV_NS}propstat")
        if propstat is None:
            continue
        prop = propstat.find(f"{DAV_NS}prop")
        restype = prop.find(f"{DAV_NS}resourcetype")
        if restype is None or restype.find(resource_tag) is None:
            continue
        path = unquote(href.rstrip("/").split("/")[-1])
        name = prop.findtext(f"{DAV_NS}displayname") or path
        results.append({"name": name, "path": path})
    return results


def _parse_dav_items(xml_text: str, data_tag: str, summarize) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for resp in root.findall(f"{DAV_NS}response"):
        href = resp.findtext(f"{DAV_NS}href") or ""
        propstat = resp.find(f"{DAV_NS}propstat")
        if propstat is None:
            continue
        prop = propstat.find(f"{DAV_NS}prop")
        data = prop.findtext(data_tag)
        if not data:
            continue
        uid = unquote(href.rstrip("/").split("/")[-1])
        uid = uid[:-4] if uid.endswith(".ics") or uid.endswith(".vcf") else uid
        items.append(summarize(uid, data))
    return items


def _event_summary(ev) -> dict:
    return {
        "uid": ev.uid.value if hasattr(ev, "uid") else None,
        "summary": ev.summary.value if hasattr(ev, "summary") else None,
        "start": _fmt_dt(ev.dtstart.value) if hasattr(ev, "dtstart") else None,
        "end": _fmt_dt(ev.dtend.value) if hasattr(ev, "dtend") else None,
        "location": ev.location.value if hasattr(ev, "location") else None,
        "recurring": hasattr(ev, "rrule") or hasattr(ev, "recurrence_id"),
    }


def _parse_expanded_events(xml_text: str) -> list[dict]:
    """Parse a calendar-query REPORT response where each calendar-data blob may
    contain multiple expanded VEVENT occurrences (one per recurrence instance)."""
    root = ET.fromstring(xml_text)
    items = []
    for resp in root.findall(f"{DAV_NS}response"):
        propstat = resp.find(f"{DAV_NS}propstat")
        if propstat is None:
            continue
        prop = propstat.find(f"{DAV_NS}prop")
        data = prop.findtext(f"{CALDAV_NS}calendar-data")
        if not data:
            continue
        cal = vobject.readOne(data)
        for ev in getattr(cal, "vevent_list", []):
            items.append(_event_summary(ev))
    items.sort(key=lambda e: e["start"] or "")
    return items


def _todo_summary(vt) -> dict:
    return {
        "uid": vt.uid.value if hasattr(vt, "uid") else None,
        "summary": vt.summary.value if hasattr(vt, "summary") else None,
        "due": _fmt_dt(vt.due.value) if hasattr(vt, "due") else None,
        "status": vt.status.value if hasattr(vt, "status") else None,
        "percent_complete": int(vt.percent_complete.value) if hasattr(vt, "percent_complete") else None,
        "priority": int(vt.priority.value) if hasattr(vt, "priority") else None,
    }


def _parse_todos(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for resp in root.findall(f"{DAV_NS}response"):
        propstat = resp.find(f"{DAV_NS}propstat")
        if propstat is None:
            continue
        prop = propstat.find(f"{DAV_NS}prop")
        data = prop.findtext(f"{CALDAV_NS}calendar-data")
        if not data:
            continue
        cal = vobject.readOne(data)
        for vt in getattr(cal, "vtodo_list", []):
            items.append(_todo_summary(vt))
    items.sort(key=lambda t: t["due"] or "")
    return items


def _summarize_contact(uid: str, vcf_text: str) -> dict:
    card = vobject.readOne(vcf_text)
    return {
        "uid": uid,
        "full_name": card.fn.value if hasattr(card, "fn") else None,
        "emails": [e.value for e in getattr(card, "email_list", [])],
        "phones": [t.value for t in getattr(card, "tel_list", [])],
    }


def _event_url(calendar: str, uid: str) -> str:
    return urljoin(CALDAV_ROOT, f"{quote(calendar.strip('/'))}/{quote(uid)}.ics")


def _contact_url(addressbook: str, uid: str) -> str:
    return urljoin(CARDDAV_ROOT, f"{quote(addressbook.strip('/'))}/{quote(uid)}.vcf")


@mcp.tool()
def list_files(path: str = "/") -> list[dict]:
    """List files and folders inside a Nextcloud directory (non-recursive)."""
    body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:resourcetype/><d:getcontentlength/><d:getlastmodified/></d:prop>
</d:propfind>"""
    with _client() as c:
        r = c.request("PROPFIND", _dav_url(path), content=body,
                       headers={"Depth": "1", "Content-Type": "application/xml"})
        r.raise_for_status()
        return _parse_propfind(r.text, path)


@mcp.tool()
def read_file(path: str, max_bytes: int = 2_000_000) -> str:
    """Read a text file's contents from Nextcloud. Fails for files larger than max_bytes."""
    with _client() as c:
        r = c.get(_dav_url(path))
        r.raise_for_status()
        if len(r.content) > max_bytes:
            raise ValueError(f"File exceeds max_bytes ({len(r.content)} > {max_bytes})")
        return r.text


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in Nextcloud."""
    with _client() as c:
        r = c.put(_dav_url(path), content=content.encode("utf-8"))
        r.raise_for_status()
        return f"Wrote {len(content)} chars to {path}"


@mcp.tool()
def delete_path(path: str) -> str:
    """Delete a file or folder (recursively) in Nextcloud."""
    with _client() as c:
        r = c.delete(_dav_url(path))
        r.raise_for_status()
        return f"Deleted {path}"


@mcp.tool()
def make_directory(path: str) -> str:
    """Create a folder in Nextcloud."""
    with _client() as c:
        r = c.request("MKCOL", _dav_url(path))
        r.raise_for_status()
        return f"Created directory {path}"


@mcp.tool()
def move_path(source: str, destination: str) -> str:
    """Move or rename a file/folder in Nextcloud."""
    with _client() as c:
        r = c.request("MOVE", _dav_url(source),
                       headers={"Destination": _dav_url(destination), "Overwrite": "F"})
        r.raise_for_status()
        return f"Moved {source} -> {destination}"


@mcp.tool()
def search_files(term: str, limit: int = 20) -> list[dict]:
    """Search files by name across Nextcloud using the unified search API."""
    with _client() as c:
        r = c.get(f"{NC_HOST}/ocs/v2.php/search/providers/files/search",
                   params={"term": term, "limit": limit}, headers=OCS_HEADERS)
        r.raise_for_status()
        data = r.json()
        entries = data.get("ocs", {}).get("data", {}).get("entries", [])
        return [{"title": e.get("title"), "subline": e.get("subline"),
                  "resourceUrl": e.get("resourceUrl")} for e in entries]


@mcp.tool()
def create_share_link(path: str, password: str | None = None, expire_date: str | None = None) -> dict:
    """Create a public read-only share link for a file or folder. expire_date format: YYYY-MM-DD."""
    payload = {"path": path, "shareType": 3, "permissions": 1}
    if password:
        payload["password"] = password
    if expire_date:
        payload["expireDate"] = expire_date
    with _client() as c:
        r = c.post(f"{NC_HOST}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                    data=payload, headers=OCS_HEADERS)
        r.raise_for_status()
        share = r.json()["ocs"]["data"]
        return {"url": share.get("url"), "id": share.get("id"), "path": share.get("path")}


@mcp.tool()
def list_shares(path: str | None = None) -> list[dict]:
    """List active shares, optionally filtered to a specific path."""
    params = {"path": path} if path else {}
    with _client() as c:
        r = c.get(f"{NC_HOST}/ocs/v2.php/apps/files_sharing/api/v1/shares",
                   params=params, headers=OCS_HEADERS)
        r.raise_for_status()
        data = r.json()["ocs"]["data"]
        return [{"id": s.get("id"), "path": s.get("path"), "url": s.get("url"),
                  "share_type": s.get("share_type")} for s in data]


@mcp.tool()
def list_calendars() -> list[dict]:
    """List available Nextcloud calendars (name and path)."""
    return _list_collections(CALDAV_ROOT, f"{CALDAV_NS}calendar")


@mcp.tool()
def list_events(calendar: str, start: str, end: str) -> list[dict]:
    """List events in a Nextcloud calendar between start and end (ISO date/datetime
    strings, e.g. '2026-08-01' or '2026-08-01T00:00:00'). Recurring events are expanded
    server-side, so each occurrence in range is returned separately (marked
    recurring=true), not just the master event."""
    range_start = _parse_dt(start).astimezone(ICAL_UTC).strftime('%Y%m%dT%H%M%SZ')
    range_end = _parse_dt(end).astimezone(ICAL_UTC).strftime('%Y%m%dT%H%M%SZ')
    body = f"""<?xml version="1.0"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/>
    <c:calendar-data>
      <c:expand start="{range_start}" end="{range_end}"/>
    </c:calendar-data>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{range_start}" end="{range_end}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""
    url = urljoin(CALDAV_ROOT, quote(calendar.strip("/")) + "/")
    with _client() as c:
        r = c.request("REPORT", url, content=body,
                       headers={"Depth": "1", "Content-Type": "application/xml"})
        r.raise_for_status()
    return _parse_expanded_events(r.text)


@mcp.tool()
def get_event(calendar: str, uid: str) -> dict:
    """Get full details (including description) of a calendar event by uid."""
    with _client() as c:
        r = c.get(_event_url(calendar, uid))
        r.raise_for_status()
    ev = vobject.readOne(r.text).vevent
    return {
        "uid": uid,
        "summary": ev.summary.value if hasattr(ev, "summary") else None,
        "start": _fmt_dt(ev.dtstart.value) if hasattr(ev, "dtstart") else None,
        "end": _fmt_dt(ev.dtend.value) if hasattr(ev, "dtend") else None,
        "location": ev.location.value if hasattr(ev, "location") else None,
        "description": ev.description.value if hasattr(ev, "description") else None,
    }


@mcp.tool()
def create_event(calendar: str, summary: str, start: str, end: str,
                  location: str | None = None, description: str | None = None,
                  all_day: bool = False) -> dict:
    """Create an event in a Nextcloud calendar. start/end are ISO date ('2026-08-20')
    or datetime ('2026-08-20T10:00:00') strings; set all_day=True for whole-day events."""
    uid = str(uuid.uuid4())
    cal = vobject.iCalendar()
    ev = cal.add("vevent")
    ev.add("uid").value = uid
    ev.add("summary").value = summary
    if all_day:
        ev.add("dtstart").value = _parse_dt(start).date()
        ev.add("dtend").value = _parse_dt(end).date()
    else:
        ev.add("dtstart").value = _parse_dt(start)
        ev.add("dtend").value = _parse_dt(end)
    ev.add("dtstamp").value = datetime.now(ICAL_UTC)
    if location:
        ev.add("location").value = location
    if description:
        ev.add("description").value = description
    with _client() as c:
        r = c.put(_event_url(calendar, uid), content=cal.serialize().encode("utf-8"),
                   headers={"Content-Type": "text/calendar; charset=utf-8"})
        r.raise_for_status()
    return {"uid": uid, "summary": summary, "start": start, "end": end}


@mcp.tool()
def update_event(calendar: str, uid: str, summary: str | None = None, start: str | None = None,
                  end: str | None = None, location: str | None = None,
                  description: str | None = None) -> dict:
    """Update fields of an existing calendar event. Only the fields passed are changed."""
    with _client() as c:
        r = c.get(_event_url(calendar, uid))
        r.raise_for_status()
        cal = vobject.readOne(r.text)
        ev = cal.vevent
        if summary is not None:
            _set_field(ev, "summary", summary)
        if start is not None:
            _set_field(ev, "dtstart", _parse_dt(start))
        if end is not None:
            _set_field(ev, "dtend", _parse_dt(end))
        if location is not None:
            _set_field(ev, "location", location)
        if description is not None:
            _set_field(ev, "description", description)
        r2 = c.put(_event_url(calendar, uid), content=cal.serialize().encode("utf-8"),
                    headers={"Content-Type": "text/calendar; charset=utf-8"})
        r2.raise_for_status()
    return {"uid": uid, "updated": True}


@mcp.tool()
def delete_event(calendar: str, uid: str) -> str:
    """Delete a calendar event by uid."""
    with _client() as c:
        r = c.delete(_event_url(calendar, uid))
        r.raise_for_status()
    return f"Deleted event {uid}"


@mcp.tool()
def list_tasks(calendar: str, include_completed: bool = True) -> list[dict]:
    """List tasks (VTODO) in a Nextcloud calendar/task list. Set include_completed=False
    to only return tasks that are not yet COMPLETED."""
    body = """<?xml version="1.0"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VTODO"/>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""
    url = urljoin(CALDAV_ROOT, quote(calendar.strip("/")) + "/")
    with _client() as c:
        r = c.request("REPORT", url, content=body,
                       headers={"Depth": "1", "Content-Type": "application/xml"})
        r.raise_for_status()
    tasks = _parse_todos(r.text)
    if not include_completed:
        tasks = [t for t in tasks if t["status"] != "COMPLETED"]
    return tasks


@mcp.tool()
def get_task(calendar: str, uid: str) -> dict:
    """Get full details (including description) of a task by uid."""
    with _client() as c:
        r = c.get(_event_url(calendar, uid))
        r.raise_for_status()
    vt = vobject.readOne(r.text).vtodo
    summary = _todo_summary(vt)
    summary["description"] = vt.description.value if hasattr(vt, "description") else None
    return summary


@mcp.tool()
def create_task(calendar: str, summary: str, due: str | None = None,
                 description: str | None = None, priority: int | None = None) -> dict:
    """Create a task (VTODO) in a Nextcloud calendar/task list. due is an ISO date
    ('2026-08-20') or datetime ('2026-08-20T10:00:00') string. priority is 0-9
    (1=highest, 9=lowest, 0/None=undefined), matching the iCalendar VTODO convention."""
    uid = str(uuid.uuid4())
    cal = vobject.iCalendar()
    vt = cal.add("vtodo")
    vt.add("uid").value = uid
    vt.add("summary").value = summary
    vt.add("dtstamp").value = datetime.now(ICAL_UTC)
    vt.add("status").value = "NEEDS-ACTION"
    if due:
        vt.add("due").value = _parse_dt(due)
    if description:
        vt.add("description").value = description
    if priority is not None:
        vt.add("priority").value = priority
    with _client() as c:
        r = c.put(_event_url(calendar, uid), content=cal.serialize().encode("utf-8"),
                   headers={"Content-Type": "text/calendar; charset=utf-8"})
        r.raise_for_status()
    return {"uid": uid, "summary": summary, "due": due}


@mcp.tool()
def update_task(calendar: str, uid: str, summary: str | None = None, due: str | None = None,
                 description: str | None = None, completed: bool | None = None,
                 percent_complete: int | None = None, priority: int | None = None) -> dict:
    """Update fields of an existing task. Only the fields passed are changed. Set
    completed=True to mark the task COMPLETED (percent_complete is set to 100 and a
    COMPLETED timestamp is stamped); completed=False reopens it as NEEDS-ACTION."""
    with _client() as c:
        r = c.get(_event_url(calendar, uid))
        r.raise_for_status()
        cal = vobject.readOne(r.text)
        vt = cal.vtodo
        if summary is not None:
            _set_field(vt, "summary", summary)
        if due is not None:
            _set_field(vt, "due", _parse_dt(due))
        if description is not None:
            _set_field(vt, "description", description)
        if percent_complete is not None:
            _set_field(vt, "percent-complete", percent_complete)
        if priority is not None:
            _set_field(vt, "priority", priority)
        if completed is True:
            _set_field(vt, "status", "COMPLETED")
            _set_field(vt, "percent-complete", 100)
            _set_field(vt, "completed", datetime.now(ICAL_UTC))
        elif completed is False:
            _set_field(vt, "status", "NEEDS-ACTION")
        r2 = c.put(_event_url(calendar, uid), content=cal.serialize().encode("utf-8"),
                    headers={"Content-Type": "text/calendar; charset=utf-8"})
        r2.raise_for_status()
    return {"uid": uid, "updated": True}


@mcp.tool()
def delete_task(calendar: str, uid: str) -> str:
    """Delete a task by uid."""
    with _client() as c:
        r = c.delete(_event_url(calendar, uid))
        r.raise_for_status()
    return f"Deleted task {uid}"


@mcp.tool()
def list_addressbooks() -> list[dict]:
    """List available Nextcloud address books (name and path)."""
    return _list_collections(CARDDAV_ROOT, f"{CARDDAV_NS}addressbook")


@mcp.tool()
def list_contacts(addressbook: str) -> list[dict]:
    """List contacts (uid, full name, emails, phones) in a Nextcloud address book."""
    body = """<?xml version="1.0"?>
<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
  <d:prop><d:getetag/><c:address-data/></d:prop>
</c:addressbook-query>"""
    url = urljoin(CARDDAV_ROOT, quote(addressbook.strip("/")) + "/")
    with _client() as c:
        r = c.request("REPORT", url, content=body,
                       headers={"Depth": "1", "Content-Type": "application/xml"})
        r.raise_for_status()
    return _parse_dav_items(r.text, f"{CARDDAV_NS}address-data", _summarize_contact)


@mcp.tool()
def get_contact(addressbook: str, uid: str) -> dict:
    """Get full details of a contact by uid, including organization if set."""
    with _client() as c:
        r = c.get(_contact_url(addressbook, uid))
        r.raise_for_status()
    card = vobject.readOne(r.text)
    return {
        "uid": uid,
        "full_name": card.fn.value if hasattr(card, "fn") else None,
        "emails": [e.value for e in getattr(card, "email_list", [])],
        "phones": [t.value for t in getattr(card, "tel_list", [])],
        "org": card.org.value[0] if hasattr(card, "org") and card.org.value else None,
    }


@mcp.tool()
def create_contact(addressbook: str, full_name: str, email: str | None = None,
                    phone: str | None = None, org: str | None = None) -> dict:
    """Create a contact in a Nextcloud address book."""
    uid = str(uuid.uuid4())
    card = vobject.vCard()
    card.add("uid").value = uid
    card.add("fn").value = full_name
    card.add("n").value = vobject.vcard.Name(family=full_name)
    if email:
        card.add("email").value = email
    if phone:
        card.add("tel").value = phone
    if org:
        card.add("org").value = [org]
    with _client() as c:
        r = c.put(_contact_url(addressbook, uid), content=card.serialize().encode("utf-8"),
                   headers={"Content-Type": "text/vcard; charset=utf-8"})
        r.raise_for_status()
    return {"uid": uid, "full_name": full_name}


@mcp.tool()
def update_contact(addressbook: str, uid: str, full_name: str | None = None,
                    email: str | None = None, phone: str | None = None,
                    org: str | None = None) -> dict:
    """Update fields of an existing contact. Only the fields passed are changed."""
    with _client() as c:
        r = c.get(_contact_url(addressbook, uid))
        r.raise_for_status()
        card = vobject.readOne(r.text)
        if full_name is not None:
            _set_field(card, "fn", full_name)
        if email is not None:
            _set_field(card, "email", email)
        if phone is not None:
            _set_field(card, "tel", phone)
        if org is not None:
            _set_field(card, "org", [org])
        r2 = c.put(_contact_url(addressbook, uid), content=card.serialize().encode("utf-8"),
                    headers={"Content-Type": "text/vcard; charset=utf-8"})
        r2.raise_for_status()
    return {"uid": uid, "updated": True}


@mcp.tool()
def delete_contact(addressbook: str, uid: str) -> str:
    """Delete a contact by uid."""
    with _client() as c:
        r = c.delete(_contact_url(addressbook, uid))
        r.raise_for_status()
    return f"Deleted contact {uid}"


@mcp.tool()
def list_talk_conversations() -> list[dict]:
    """List Nextcloud Talk conversations (rooms) visible to this user, with their token,
    display name, type and unread message count."""
    with _client() as c:
        r = c.get(f"{SPREED_API_V4}/room", headers=OCS_HEADERS)
        r.raise_for_status()
    rooms = r.json()["ocs"]["data"]
    return [{
        "token": rm.get("token"),
        "name": rm.get("displayName"),
        "type": rm.get("type"),
        "unread_messages": rm.get("unreadMessages"),
        "last_activity": rm.get("lastActivity"),
    } for rm in rooms]


@mcp.tool()
def get_talk_messages(token: str, last_known_message_id: int | None = None,
                       limit: int = 100) -> list[dict]:
    """Read chat messages from a Nextcloud Talk conversation identified by its token
    (see list_talk_conversations). Pass last_known_message_id (from a previous call) to
    fetch only messages after it; omit to get the most recent `limit` messages."""
    params = {"lookIntoFuture": 0, "limit": limit}
    if last_known_message_id:
        params["lastKnownMessageId"] = last_known_message_id
        params["includeLastKnown"] = 0
    with _client() as c:
        r = c.get(f"{SPREED_API}/chat/{quote(token)}", params=params, headers=OCS_HEADERS)
        r.raise_for_status()
    msgs = r.json()["ocs"]["data"]
    return [{
        "id": m.get("id"),
        "actor": m.get("actorDisplayName"),
        "message": m.get("message"),
        "timestamp": m.get("timestamp"),
    } for m in msgs]


@mcp.tool()
def send_talk_message(token: str, message: str) -> dict:
    """Send a chat message to a Nextcloud Talk conversation identified by its token
    (see list_talk_conversations)."""
    with _client() as c:
        r = c.post(f"{SPREED_API}/chat/{quote(token)}", data={"message": message},
                    headers=OCS_HEADERS)
        r.raise_for_status()
    data = r.json()["ocs"]["data"]
    return {"id": data.get("id"), "timestamp": data.get("timestamp")}


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=BIND_HOST, port=BIND_PORT)
