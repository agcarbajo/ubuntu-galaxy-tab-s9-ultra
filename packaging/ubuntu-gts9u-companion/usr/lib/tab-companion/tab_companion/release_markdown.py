# SPDX-License-Identifier: MIT
"""Render Markdown tokens as bounded, escaped Pango markup, never HTML."""
from html import escape
import re
from urllib.parse import urlsplit
from markdown_it import MarkdownIt


def inline(tokens):
    result, links = [], []
    styles = {"strong": "b", "em": "i", "s": "s"}
    for token in tokens or []:
        kind = token.type
        base = kind.removesuffix("_open").removesuffix("_close")
        if base in styles:
            result.append(f"<{styles[base]}>" if token.nesting == 1 else f"</{styles[base]}>")
        elif kind == "code_inline":
            result.append("<tt>" + escape(token.content) + "</tt>")
        elif kind == "link_open":
            href = token.attrGet("href") or ""
            allowed = urlsplit(href).scheme.lower() in ("https", "http", "mailto")
            links.append(allowed)
            result.append('<a href="' + escape(href, quote=True) + '">' if allowed else "")
        elif kind == "link_close":
            result.append("</a>" if links.pop() else "")
        elif kind in ("softbreak", "hardbreak"):
            result.append("\n")
        elif kind == "image":
            # Alt text only: opening the page must not fetch remote images.
            result.append(inline(token.children) or escape(token.content))
        else:
            result.append(escape(token.content))
    return "".join(result)


def markup(source):
    source = re.sub(r"<!--.*?-->", "", source or "", flags=re.S)[:128 * 1024]
    parser = MarkdownIt("commonmark", {"html": False, "maxNesting": 20}).enable(["table", "strikethrough"])
    output, lists = [], []
    for token in parser.parse(source):
        kind = token.type
        if kind == "inline":
            output.append(inline(token.children))
        elif kind == "heading_open":
            size = {"h1": "x-large", "h2": "large"}.get(token.tag, "medium")
            output.append(f'<span size="{size}" weight="bold">')
        elif kind == "heading_close":
            output.append("</span>\n\n")
        elif kind in ("fence", "code_block"):
            output.append("<tt>" + escape(token.content.rstrip()) + "</tt>\n\n")
        elif kind in ("bullet_list_open", "ordered_list_open"):
            lists.append(None if kind == "bullet_list_open" else int(token.attrGet("start") or 1))
        elif kind in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
            if not lists:
                output.append("\n")
        elif kind == "list_item_open":
            prefix = "• " if lists[-1] is None else f"{lists[-1]}. "
            if lists[-1] is not None:
                lists[-1] += 1
            output.append("  " * (len(lists) - 1) + prefix)
        elif kind == "list_item_close":
            output.append("\n")
        elif kind == "paragraph_close":
            output.append("\n\n" if not token.hidden else "")
        elif kind == "blockquote_open":
            output.append("<i>❯ ")
        elif kind == "blockquote_close":
            output.append("</i>\n")
        elif kind == "hr":
            output.append("────────────\n\n")
        elif kind == "th_open":
            output.append("<b>")
        elif kind == "th_close":
            output.append("</b>  │  ")
        elif kind == "td_close":
            output.append("  │  ")
        elif kind == "tr_close":
            output.append("\n")
        elif kind == "table_close":
            output.append("\n")
    return "".join(output).strip()
