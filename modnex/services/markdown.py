"""Markdown y HTML de las fichas de mods: conversión y saneado a una lista de etiquetas permitidas."""

import html
import re
from html.parser import HTMLParser




SAFE_URL = re.compile(r"https?://[^\s\"'<>]{4,600}")


def _safe_href(url):
    return url if url and SAFE_URL.fullmatch(url) else None


_HTML_TAG_START = re.compile(r"^\s{0,3}<(/?[a-zA-Z][a-zA-Z0-9-]*|!--)")


_SAFE_LINK = re.compile(r"https?://[^\s\"'<>]{4,600}")


def _link_href(url):
    return url if _SAFE_LINK.fullmatch(url or "") else None


def _inline(t):
    """Markdown en línea. El texto se escapa; las etiquetas HTML se dejan pasar y las filtra después sanitize_html."""
    held = []

    def hold(h):
        held.append(h)
        return f"\x00{len(held) - 1}\x00"

    t = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~|<>])", lambda m: hold(html.escape(m.group(1), quote=True)), t)
    t = re.sub(r"`([^`\n]+)`", lambda m: hold("<code>" + html.escape(m.group(1), quote=True) + "</code>"), t)

    def image(m):
        href = _link_href(m.group(2))
        if not href:
            return html.escape(m.group(0), quote=True)
        return hold(f'<img src="{html.escape(href, quote=True)}" alt="{html.escape(m.group(1), quote=True)}" loading="lazy">')

    def link(m):
        href = _link_href(m.group(2))
        if not href:
            return m.group(1)
        return hold(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener nofollow">{m.group(1)}</a>')

    url = r"((?:[^\s()]|\([^\s()]*\))+)"
    t = re.sub(r"!\[([^\]\n]{0,200})\]\(" + url + r"(?:\s+\"[^\"]*\")?\)", image, t)
    t = re.sub(r"\[([^\]\n]{1,300})\]\(" + url + r"(?:\s+\"[^\"]*\")?\)", link, t)
    t = re.sub(r"<(https?://[^\s>]{4,600})>", lambda m: hold(
        f'<a href="{html.escape(m.group(1), quote=True)}" target="_blank" rel="noopener nofollow">{html.escape(m.group(1), quote=False)}</a>')
        if _link_href(m.group(1)) else m.group(0), t)
    t = re.sub(r"</?[a-zA-Z][^<>\n]{0,300}>", lambda m: hold(m.group(0)), t)
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__",
               lambda m: "<strong>" + (m.group(1) or m.group(2)) + "</strong>", t)
    t = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", t)
    t = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])|(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])",
               lambda m: "<em>" + (m.group(1) or m.group(2)) + "</em>", t)
    t = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], t)
    return t


def _heading_level(n):
    return min(n + 1, 5)  # la ficha ya tiene un h1: los títulos del mod empiezan en h2


def _is_block_start(line):
    return bool(re.match(r"^(#{1,6})\s", line) or re.match(r"^\s*(```|~~~)", line)
                or re.match(r"^\s*(\*\s*){3,}$|^\s*(-\s*){3,}$|^\s*(_\s*){3,}$", line)
                or re.match(r"^\s*>", line) or re.match(r"^\s*([-*+]|\d+[.)])\s+", line)
                or _HTML_TAG_START.match(line))


def _table_sep(line):
    return bool(re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", line))


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_list(lines, i):
    base = len(lines[i]) - len(lines[i].lstrip())
    first = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", lines[i])
    ordered = first.group(1)[0].isdigit()
    tag = "ol" if ordered else "ul"
    items = []
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            if i + 1 < len(lines) and lines[i + 1].strip():
                nxt_indent = len(lines[i + 1]) - len(lines[i + 1].lstrip())
                if nxt_indent > base or (nxt_indent == base and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i + 1])):
                    if items:
                        items[-1][1].append("")
                    i += 1
                    continue
            break
        indent = len(ln) - len(ln.lstrip())
        m = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", ln)
        if m and indent == base and m.group(1)[0].isdigit() != ordered:
            break  # otra lista distinta: empieza después
        if m and indent == base:
            items.append([m.group(2), []])
        elif indent > base and items:
            items[-1][1].append(ln[base + 2:] if len(ln) > base + 2 else ln.lstrip())
        elif items and indent == base and not _is_block_start(ln):
            items[-1][0] += " " + ln.strip()  # continuación perezosa
        else:
            break
        i += 1
    out = [f"<{tag}>"]
    for text, sub in items:
        body = _inline(text)
        if sub and any(x.strip() for x in sub):
            body += render_blocks(sub)
        out.append(f"<li>{body}</li>")
    out.append(f"</{tag}>")
    return "".join(out), i


def render_blocks(lines):
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        fence = re.match(r"^\s*(```+|~~~+)\s*([\w+.-]*)", ln)
        if fence:
            marker, code = fence.group(1), []
            i += 1
            while i < n and not lines[i].strip().startswith(marker):
                code.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(fence.group(2), quote=True)}"' if fence.group(2) else ""
            out.append(f"<pre><code{cls}>{html.escape(chr(10).join(code), quote=True)}</code></pre>")
            continue
        h = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if h:
            lvl = _heading_level(len(h.group(1)))
            out.append(f"<h{lvl}>{_inline(h.group(2))}</h{lvl}>")
            i += 1
            continue
        if re.match(r"^\s*(\*\s*){3,}$|^\s*(-\s*){3,}$|^\s*(_\s*){3,}$", ln):
            out.append("<hr>")
            i += 1
            continue
        if re.match(r"^\s*>", ln):
            quote = []
            while i < n and re.match(r"^\s*>", lines[i]):
                quote.append(re.sub(r"^\s*> ?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render_blocks(quote)}</blockquote>")
            continue
        if re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
            html_list, i = _render_list(lines, i)
            out.append(html_list)
            continue
        if "|" in ln and i + 1 < n and _table_sep(lines[i + 1]):
            head = _cells(ln)
            aligns = []
            for c in _cells(lines[i + 1]):
                aligns.append("right" if c.endswith(":") and not c.startswith(":") else "center" if c.startswith(":") and c.endswith(":") else "")
            i += 2
            rows = []
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            def cell(tag, c, k):
                al = f' style="text-align:{aligns[k]}"' if k < len(aligns) and aligns[k] else ""
                return f"<{tag}{al}>{_inline(c)}</{tag}>"
            body = "".join("<tr>" + "".join(cell("td", c, k) for k, c in enumerate(r)) + "</tr>" for r in rows)
            out.append("<table><thead><tr>" + "".join(cell("th", c, k) for k, c in enumerate(head))
                       + "</tr></thead><tbody>" + body + "</tbody></table>")
            continue
        if _HTML_TAG_START.match(ln):
            raw = []
            while i < n and lines[i].strip():
                raw.append(lines[i])
                i += 1
            out.append("\n".join(raw))
            continue
        para = []
        while i < n and lines[i].strip() and not (para and _is_block_start(lines[i])):
            para.append(lines[i])
            i += 1
        if para:
            parts = []
            for k, pl in enumerate(para):
                hard = pl.endswith("  ") or pl.endswith("\\")
                txt = _inline(pl.strip().rstrip("\\"))
                parts.append(txt + ("<br>" if hard and k < len(para) - 1 else ""))
            out.append("<p>" + " ".join(parts) + "</p>")
    return "\n".join(out)


def render_markdown(text):
    return render_blocks((text or "").replace("\r\n", "\n").replace("\t", "    ")[:120000].split("\n"))


def md_to_html(text):
    """Markdown de Modrinth/CurseForge a HTML seguro (el HTML crudo también pasa por el filtro)."""
    out = sanitize_html(render_markdown(text))
    # párrafos vacíos (espaciadores habituales en Modrinth): fuera, o dejan huecos enormes
    return re.sub(r"<p>(?:\s|&nbsp;|\xa0|<br>)*</p>", "", out)


class _SafeHTML(HTMLParser):
    """Filtro de lista blanca para la descripción HTML que devuelve CurseForge."""
    ALLOWED = {"p", "br", "strong", "b", "em", "i", "u", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5",
               "code", "pre", "blockquote", "a", "img", "hr", "span", "div", "center", "table", "tr", "td", "th", "thead", "tbody",
               "details", "summary", "kbd", "sub", "sup", "small", "del", "s", "mark"}
    VOID = {"br", "hr", "img"}
    KEEP_ATTR = {"code": ("class",), "pre": ("class",), "th": ("style",), "td": ("style",)}
    DROP = {"script", "style", "iframe", "object", "embed", "svg", "form", "input", "button", "video", "audio", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.drop = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.drop += 1
            return
        if self.drop or tag not in self.ALLOWED:
            return
        a = dict(attrs)
        if tag == "a":
            href = _safe_href(a.get("href"))
            if not href:
                self.out.append("<span>"); self.stack.append("span"); return
            self.out.append(f'<a href="{html.escape(href, quote=True)}" target="_blank" rel="noopener nofollow">')
            self.stack.append("a")
        elif tag == "img":
            src = _safe_href(a.get("src"))
            if src:
                self.out.append(f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(a.get("alt") or "", quote=True)}" loading="lazy">')
        elif tag in self.VOID:
            self.out.append(f"<{tag}>")
        else:
            extra = ""
            for k in self.KEEP_ATTR.get(tag, ()):
                v = a.get(k) or ""
                if k == "class" and re.fullmatch(r"language-[A-Za-z0-9+.#-]{1,30}", v):
                    extra += f' class="{v}"'
                if k == "style" and re.fullmatch(r"text-align:\s*(left|right|center)", v):
                    extra += f' style="{v}"'
            self.out.append(f"<{tag}{extra}>")
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.DROP:
            self.drop = max(0, self.drop - 1)
            return
        if self.drop or tag not in self.stack:
            return
        while self.stack:  # cierra lo que quedó abierto dentro de este elemento
            t = self.stack.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.drop:
            self.out.append(html.escape(data, quote=True))

    def close_all(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def sanitize_html(raw):
    p = _SafeHTML()
    p.feed((raw or "")[:120000])
    p.close()
    p.close_all()
    return "".join(p.out)


def _body_to_html(body):
    """Descripción de Modrinth/CurseForge: markdown (con HTML embebido) renderizado y filtrado."""
    return md_to_html(body or "")
