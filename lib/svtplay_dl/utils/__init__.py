# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
from __future__ import absolute_import
import sys
import socket
import logging
import re
import xml.etree.ElementTree as ET
import json
import time
import unicodedata
try:
    import HTMLParser
except ImportError:
    import html.parser as HTMLParser

is_py2 = (sys.version_info[0] == 2)
is_py3 = (sys.version_info[0] == 3)
is_py2_old = (sys.version_info < (2, 7))

# Used for UA spoofing in get_http_data()
FIREFOX_UA = 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-GB; rv:1.9.0.3) Gecko/2008092417 Firefox/3.0.3'

from svtplay_dl.utils.urllib import build_opener, Request, HTTPCookieProcessor, \
                                    HTTPRedirectHandler, HTTPError, URLError, \
                                    addinfourl, CookieJar

log = logging.getLogger('svtplay_dl')
progress_stream = sys.stderr

class NoRedirectHandler(HTTPRedirectHandler):
    def __init__(self):
        pass

    def http_error_302(self, req, fp, code, msg, headers):
        infourl = addinfourl(fp, headers, req.get_full_url())
        infourl.status = code
        infourl.code = code
        return infourl
    http_error_300 = http_error_302
    http_error_301 = http_error_302
    http_error_303 = http_error_302
    http_error_307 = http_error_302

def get_http_data(url, header=None, data=None, useragent=FIREFOX_UA,
                  referer=None, cookiejar=None):
    """ Get the page to parse it for streams """
    if not cookiejar:
        cookiejar = CookieJar()

    log.debug("HTTP getting %r", url)
    starttime = time.time()

    request = Request(url)
    standard_header = {'Referer': referer, 'User-Agent': useragent}
    for key, value in [head for head in standard_header.items() if head[1]]:
        request.add_header(key, value)
    if header:
        for key, value in [head for head in header.items() if head[1]]:
            request.add_header(key, value)
    if data:
        request.add_data(data)

    opener = build_opener(HTTPCookieProcessor(cookiejar))

    try:
        response = opener.open(request)
    except HTTPError as e:
        log.error("Something wrong with that url")
        log.error("Error code: %s", e.code)
        sys.exit(5)
    except URLError as e:
        log.error("Something wrong with that url")
        log.error("Error code: %s", e.reason)
        sys.exit(5)
    except ValueError as e:
        log.error("Try adding http:// before the url")
        sys.exit(5)
    if is_py3:
        data = response.read()
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            pass
    else:
        try:
            data = response.read()
        except socket.error as e:
            log.error("Lost the connection to the server")
            sys.exit(5)
    response.close()

    spent_time = time.time() - starttime
    bps = 8 * len(data) / max(spent_time, 0.001)

    log.debug("HTTP got %d bytes from %r in %.2fs (= %dbps)",
              len(data), url, spent_time, bps)

    return data

def check_redirect(url):
    opener = build_opener(NoRedirectHandler())
    opener.addheaders += [('User-Agent', FIREFOX_UA)]
    response = opener.open(url)
    if response.code in (300, 301, 302, 303, 307):
        return response.headers["location"]
    else:
        return url

def timestr(msec):
    """
    Convert a millisecond value to a string of the following
    format:

        HH:MM:SS,SS

    with 10 millisecond precision. Note the , seperator in
    the seconds.
    """
    sec = float(msec) / 1000

    hours = int(sec / 3600)
    sec -= hours * 3600

    minutes = int(sec / 60)
    sec -= minutes * 60

    output = "%02d:%02d:%05.2f" % (hours, minutes, sec)
    return output.replace(".", ",")

def norm(name):
    if name[0] == "{":
        _, tag = name[1:].split("}")
        return tag
    else:
        return name

def subtitle_tt(options, subtitle):
    i = 1
    data = ""
    skip = False
    tree = ET.ElementTree(ET.fromstring(subtitle))
    for node in tree.iter():
        tag = norm(node.tag)
        if tag == "p":
            if skip:
                data = data + "\n"
            begin = node.attrib["begin"]
            if not ("dur" in node.attrib):
                duration = node.attrib["duration"]
            else:
                duration = node.attrib["dur"]
            if not ("end" in node.attrib):
                begin2 = begin.split(":")
                duration2 = duration.split(":")
                sec = float(begin2[2]) + float(duration2[2])
                end = "%02d:%02d:%06.3f" % (int(begin[0]), int(begin[1]), sec)
            else:
                end = node.attrib["end"]
            data += '%s\n%s --> %s\n' % (i, begin.replace(".",","), end.replace(".",","))
            data += '%s\n' % node.text.strip(' \t\n\r')
            skip = True
            i += 1
        if tag == "br":
            if node.tail:
                data += '%s\n\n' % node.tail.strip(' \t\n\r')
                skip = False
    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    if filename:
        options.output = "%s.srt" % filename.group(1)
    log.info("Subtitle: %s", options.output)
    fd = open(options.output, "w")
    if is_py2:
        data = data.encode('utf8')
    fd.write(data)
    fd.close()

def subtitle_json(options, data):
    data = json.loads(data)
    number = 1
    subs = ""
    for i in data:
        subs += "%s\n%s --> %s\n" % (number, timestr(int(i["startMillis"])), timestr(int(i["endMillis"])))
        subs += "%s\n\n" % i["text"].encode("utf-8")
        number += 1

    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    if filename:
        options.output = "%s.srt" % filename.group(1)
    log.info("Subtitle: %s", options.output)
    fd = open(options.output, "w")
    fd.write(subs)
    fd.close()

def subtitle_sami(options, data):
    tree = ET.XML(data)
    subt = tree.find("Font")
    subs = ""
    n = 0
    for i in subt.getiterator():
        if i.tag == "Subtitle":
            n = i.attrib["SpotNumber"]
            if i.attrib["SpotNumber"] == "1":
                subs += "%s\n%s --> %s\n" % (i.attrib["SpotNumber"], i.attrib["TimeIn"], i.attrib["TimeOut"])
            else:
                subs += "\n%s\n%s --> %s\n" % (i.attrib["SpotNumber"], i.attrib["TimeIn"], i.attrib["TimeOut"])
        else:
            if int(n) > 0:
                subs += "%s\n" % i.text

    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    if filename:
        options.output = "%s.srt" % filename.group(1)
    log.info("Subtitle: %s", options.output)
    fd = open(options.output, "w")
    if is_py2:
        subs = subs.encode('utf8')
    fd.write(subs)
    fd.close()

def subtitle_smi(options, data):
    recomp = re.compile(r'<SYNC Start=(\d+)>\s+<P Class=\w+>(.*)<br>\s+<SYNC Start=(\d+)>\s+<P Class=\w+>', re.M|re.I|re.U)
    number = 1
    subs = ""
    for i in recomp.finditer(str(data)):
        subs += "%s\n%s --> %s\n" % (number, timestr(i.group(1)), timestr(i.group(3)))
        text = "%s\n\n" % i.group(2)
        subs += text.replace("<br>", "\n")
        number += 1

    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    if filename:
        options.output = "%s.srt" % filename.group(1)
    log.info("Subtitle: %s", options.output)
    fd = open(options.output, "w")
    fd.write(subs)
    fd.close()

def subtitle_wsrt(options, data):
    recomp = re.compile(r"(\d+)\r\n([\d:\.]+ --> [\d:\.]+)?([^\r\n]+)?\r\n([^\r\n]+)\r\n(([^\r\n]*)\r\n)?")
    srt = ""
    for i in recomp.finditer(data):
        sub = "%s\n%s\n%s\n" % (i.group(1), i.group(2).replace(".", ","), i.group(4))
        if len(i.group(6)) > 0:
            sub += "%s\n" % i.group(6)
        sub += "\n"
        sub = re.sub('<[^>]*>', '', sub)
        srt += sub
    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    if filename:
        options.output = "%s.srt" % filename.group(1)
    log.info("Subtitle: %s", options.output)
    fd = open(options.output, "w")
    fd.write(srt)
    fd.close()

def select_quality(options, streams):
    available = sorted(streams.keys(), key=int)

    try:
        optq = int(options.quality)
    except ValueError:
        log.error("Requested quality need to be a number")
        sys.exit(4)
    if optq:
        try:
            optf = int(options.flexibleq)
        except ValueError:
            log.error("Flexible-quality need to be a number")
            sys.exit(4)
        if not optf:
            wanted = [optq]
        else:
            wanted = range(optq-optf, optq+optf+1)
    else:
        wanted = [available[-1]]

    selected = None
    for q in available:
        if q in wanted:
            selected = q
            break

    if not selected:
        log.error("Can't find that quality. Try one of: %s (or try --flexible-quality)",
                  ", ".join([str(elm) for elm in available]))
        sys.exit(4)

    return streams[selected]

def ensure_unicode(s):
    """
    Ensure string is a unicode string. If it isn't it assumed it is
    utf-8 and decodes it to a unicode string.
    """
    if (is_py2 and isinstance(s, str)) or (is_py3 and isinstance(s, bytes)):
        s = s.decode('utf-8', 'replace')
    return s

def decode_html_entities(s):
    """
    Replaces html entities with the character they represent.

        >>> print(decode_html_entities("&lt;3 &amp;"))
        <3 &
    """
    parser = HTMLParser.HTMLParser()
    def unesc(m):
        return parser.unescape(m.group())
    return re.sub(r'(&[^;]+;)', unesc, ensure_unicode(s))

def filenamify(title):
    """
    Convert a string to something suitable as a file name.

        >>> print(filenamify(u'Matlagning del 1 av 10 - R\xe4ksm\xf6rg\xe5s | SVT Play'))
        matlagning-del-1-av-10-raksmorgas-svt-play

    """
    # ensure it is unicode
    title = ensure_unicode(title)

    # NFD decomposes chars into base char and diacritical mark, which means that we will get base char when we strip out non-ascii.
    title = unicodedata.normalize('NFD', title)

    # Drop any non ascii letters/digits
    title = re.sub(r'[^a-zA-Z0-9 -]', '', title)
    # Drop any leading/trailing whitespace that may have appeared
    title = title.strip()
    # Lowercase
    title = title.lower()
    # Replace whitespace with dash
    title = re.sub(r'[-\s]+', '-', title)

    return title

def download_thumbnail(options, url):
    data = get_http_data(url)

    filename = re.search(r"(.*)\.[a-z0-9]{2,3}$", options.output)
    tbn = "%s.tbn" % filename.group(1)
    log.info("Thumbnail: %s", tbn)

    fd = open(tbn, "wb")
    fd.write(data)
    fd.close()
