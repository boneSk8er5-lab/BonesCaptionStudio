"""The Bones Caption Studio guide: reads the topic files in the "guide" folder, shows them in the app
(Help › User Guide) and saves them as one web page (build_guide.bat turns that into a PDF).

Topic files use a tiny format (see guide/topics.txt):
    # Title / ## Heading / 1. Step / - Point / > Tip / ![caption](picture.png) / | table | rows |
    **bold**, `key or exact text`, [text](topic:other-topic)
"""
import html
import os
import re
import shutil

TITLE = "Bones Caption Studio guide"
RIGHTS = ("Copyright &#169; 2026 Bones_84. All rights reserved. Download it only from the official "
          "Bones Caption Studio page on GitHub; please don&#39;t share or re-upload it.")


# ---------------------------------------------------------------------------------------------- reading
def load_topics(guide_dir):
    """[(topic id, title, markdown text)] in reading order. Missing files are skipped."""
    order_file = os.path.join(guide_dir, "topics.txt")
    if not os.path.exists(order_file):
        return []
    topics = []
    with open(order_file, encoding="utf-8") as f:
        ids = [line.strip() for line in f if line.strip() and not line.lstrip().startswith("#")]
    for topic_id in ids:
        path = os.path.join(guide_dir, topic_id + ".md")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        first = next((l for l in text.splitlines() if l.startswith("# ")), "# " + topic_id)
        topics.append((topic_id, first[2:].strip(), text))
    return topics


# ---------------------------------------------------------------------------------------------- markdown
def _inline(text, link):
    """Bold, `code` and [links](topic:x). `link(topic_id)` gives the href for a topic."""
    out, pos = [], 0
    for m in re.finditer(r"`([^`]+)`", text):          # code first, so ** inside it stays literal
        out.append(_inline_plain(text[pos:m.start()], link))
        out.append(f"<code>{html.escape(m.group(1))}</code>")
        pos = m.end()
    out.append(_inline_plain(text[pos:], link))
    return "".join(out)


def _inline_plain(text, link):
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*]+)\*(?![\w*])", r"<em>\1</em>", text)

    def repl(m):
        target = m.group(2)
        href = link(target[6:]) if target.startswith("topic:") else html.escape(target)
        return f'<a href="{href}">{m.group(1)}</a>'
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", repl, text)


def to_html(md, link, image, skip_title=False):
    """Topic text -> HTML. `image(name)` gives the src for a picture."""
    lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("# "):
            if not skip_title:
                out.append(f"<h1>{_inline(line[2:], link)}</h1>")
            i += 1
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:], link)}</h2>")
            i += 1
        elif re.match(r"!\[[^\]]*\]\([^)]+\)\s*$", line.strip()):
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
            cap = html.escape(m.group(1))
            out.append(f'<figure><img src="{image(m.group(2))}" alt="{cap}" /><figcaption>{cap}</figcaption></figure>')
            i += 1
        elif line.startswith(">"):
            tip = []
            while i < len(lines) and lines[i].startswith(">"):
                tip.append(lines[i][1:].strip())
                i += 1
            out.append(f'<div class="tip">{_inline(" ".join(tip), link)}</div>')
        elif re.match(r"\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"\d+\. ", lines[i]):
                items.append(_inline(re.sub(r"^\d+\. ", "", lines[i]), link))
                i += 1
            out.append("<ol>" + "".join(f"<li>{x}</li>" for x in items) + "</ol>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(_inline(lines[i][2:], link))
                i += 1
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                head = "".join(f"<th>{_inline(c, link)}</th>" for c in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{_inline(c, link)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><tr>{head}</tr>{body}</table>")
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|>|- |\d+\. |\||!\[)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para), link)}</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------- web page
PAGE_CSS = """
  body { font-family: "Segoe UI", Arial, sans-serif; font-size: 15px; line-height: 1.55; color: #1F1F1F;
         background: #F3F3F3; margin: 0; }
  main { max-width: 820px; margin: 0 auto; padding: 32px 24px 64px; }
  .cover { border-top: 8px solid #00ADB5; background: #222831; color: #EEEEEE; border-radius: 8px;
           padding: 28px 32px; margin-bottom: 24px; }
  .cover h1 { margin: 0 0 6px; font-size: 32px; }
  .cover p { margin: 0; color: #B8C0C8; }
  .cover p.rights { margin-top: 10px; font-size: 13px; }
  nav { background: #FFFFFF; border-radius: 8px; padding: 18px 32px; margin-bottom: 24px; }
  nav ol { margin: 8px 0 0; padding-left: 22px; }
  nav a { color: #007C82; text-decoration: none; }
  section { background: #FFFFFF; border-radius: 8px; padding: 26px 32px; margin-bottom: 24px; }
  h1 { font-size: 26px; margin: 0 0 14px; }
  h2 { font-size: 19px; margin: 26px 0 8px; }
  a { color: #007C82; }
  code { font-family: Consolas, monospace; background: #EBEBEB; border: 1px solid #DDDDDD; border-radius: 4px;
         padding: 0 5px; font-size: 13.5px; }
  ol li, ul li { margin-bottom: 6px; }
  figure { margin: 18px 0; }
  figure img { max-width: 100%; border: 1px solid #DDDDDD; border-radius: 6px; }
  figcaption { color: #5F5F5F; font-size: 13px; margin-top: 4px; }
  .tip { border-left: 4px solid #00ADB5; background: #EAF7F8; border-radius: 4px; padding: 10px 14px; margin: 16px 0; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th, td { border: 1px solid #DDDDDD; padding: 6px 10px; text-align: left; vertical-align: top; }
  th { background: #F3F3F3; }
  footer { color: #5F5F5F; font-size: 12.5px; text-align: center; padding: 8px 24px 0; }
  @media print {
    body { background: #FFFFFF; font-size: 12pt; }
    main { padding: 0; max-width: none; }
    .cover, nav, section { border-radius: 0; margin: 0 0 18px; }
    nav, section { padding: 0; }
    section { break-before: page; }
    figure, .tip, table { break-inside: avoid; }
    a { color: #1F1F1F; text-decoration: none; }
  }
"""


def export_html(guide_dir, out_dir, version=""):
    """Write out_dir/guide.html and out_dir/images/*. Returns the page's path."""
    topics = load_topics(guide_dir)
    if not topics:
        raise FileNotFoundError(f"No guide topics found in {guide_dir}")
    os.makedirs(out_dir, exist_ok=True)
    src_images = os.path.join(guide_dir, "images")
    if os.path.isdir(src_images):
        dst_images = os.path.join(out_dir, "images")
        os.makedirs(dst_images, exist_ok=True)
        for name in os.listdir(src_images):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                shutil.copy2(os.path.join(src_images, name), os.path.join(dst_images, name))

    link = lambda topic_id: f"#{topic_id}"
    image = lambda name: "images/" + html.escape(name)
    nav = "".join(f'<li><a href="#{tid}">{html.escape(title)}</a></li>' for tid, title, _ in topics)
    sections = "".join(f'<section id="{tid}">\n{to_html(md, link, image)}\n</section>\n' for tid, title, md in topics)
    ver = f" Version {html.escape(version)}." if version else ""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{TITLE}</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<main><div class="cover"><h1>{TITLE}</h1><p>Word-by-word captions for your videos.{ver}</p>
<p class="rights">{RIGHTS}</p></div>
<nav><strong>In this guide</strong><ol>{nav}</ol></nav>
{sections}<footer>{RIGHTS}</footer></main>
</body>
</html>
"""
    path = os.path.join(out_dir, "guide.html")
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(page)
    return path


# ---------------------------------------------------------------------------------------------- in the app
def make_dialog(parent, guide_dir, version="", start_topic=None, export_dir=None):
    """Help › User Guide: topics on the left, the topic on the right. Uses the app's dark theme."""
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices, QImageReader
    from PySide6.QtWidgets import (QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
                                   QSplitter, QTextBrowser, QVBoxLayout)

    topics = load_topics(guide_dir)
    dialog = QDialog(parent)
    dialog.setWindowTitle(TITLE)
    dialog.resize(1080, 760)
    accent = getattr(parent, "accent_color", None) or "#00ADB5"
    accent_text = getattr(parent, "accent_text", None) or "#121212"
    dialog.setStyleSheet(
        "QListWidget, QTextBrowser { background-color: #1E1E1E; color: #E0E0E0; border: 1px solid #2D2D2D;"
        " border-radius: 8px; font-size: 14px; }"
        "QListWidget { padding: 6px; } QListWidget::item { padding: 7px 8px; border-radius: 5px; }"
        f"QListWidget::item:selected {{ background-color: {accent}; color: {accent_text}; }}"
        "QListWidget::item:hover:!selected { background-color: #2A2A2A; }"
        "QTextBrowser { padding: 10px 18px; }")
    layout = QVBoxLayout(dialog)
    split = QSplitter(Qt.Horizontal)
    listing = QListWidget()
    listing.setObjectName("GuideTopics")
    listing.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    listing.setWordWrap(True)
    page = QTextBrowser()
    page.setOpenLinks(False)
    page.setSearchPaths([os.path.join(guide_dir, "images")])
    page.document().setDefaultStyleSheet(
        "h1 { font-size: 22px; color: #FFFFFF; } "
        + f"h2 {{ font-size: 16px; color: {accent}; margin-top: 14px; }} a {{ color: {accent}; }} "
        + "code { font-family: Consolas, monospace; } p, li { line-height: 140%; } "
        "td, th { padding: 4px 8px; } th { background-color: #393E46; } .tip { background-color: #2B3A40; }")
    split.addWidget(listing)
    split.addWidget(page)
    split.setStretchFactor(1, 1)
    split.setSizes([260, 820])
    layout.addWidget(split, 1)

    ids = [tid for tid, _t, _m in topics]

    def show(index):
        if 0 <= index < len(topics):
            tid, title, md = topics[index]
            body = to_html(md, lambda t: f"topic:{t}", lambda name: name)
            # QTextBrowser can't style <div>/<figure> much: make tips a one-cell table, pictures fit the width
            body = re.sub(r'<div class="tip">(.*?)</div>',
                          r'<table width="100%" cellpadding="10" class="tip"><tr><td>💡 \1</td></tr></table>', body)
            def picture(m):
                size = QImageReader(os.path.join(guide_dir, "images", m.group(1))).size()
                width = min(size.width(), 740) if size.isValid() else 740
                return (f'<p><img src="{m.group(1)}" width="{width}" /><br/>'
                        f'<span style="color:#9A9A9A">{m.group(2)}</span></p>')
            body = re.sub(r'<figure><img src="([^"]+)" alt="([^"]*)" /><figcaption>.*?</figcaption></figure>',
                          picture, body)
            body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="5" width="100%">')
            body = body.replace("<code>", '<code style="background-color:#333A44; color:#FFFFFF;">')
            page.setHtml(body)
            page.verticalScrollBar().setValue(0)

    def clicked(url):
        target = url.toString()
        if target.startswith("topic:") and target[6:] in ids:
            listing.setCurrentRow(ids.index(target[6:]))
        elif target.startswith("http"):
            QDesktopServices.openUrl(url)

    for tid, title, _m in topics:
        listing.addItem(QListWidgetItem(title))
    listing.currentRowChanged.connect(show)
    page.anchorClicked.connect(clicked)

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    if export_dir:
        web = QPushButton("Open in Web Browser")
        web.setToolTip("Open the whole guide as one page, ready to read or print")

        def open_web():
            try:
                QDesktopServices.openUrl(QUrl.fromLocalFile(export_html(guide_dir, export_dir, version)))
            except Exception as exc:
                page.setHtml(f"<p>Couldn't save the guide: {html.escape(str(exc))}</p>")
        web.clicked.connect(open_web)
        buttons.addWidget(web)
    close = QPushButton("Close")
    close.clicked.connect(dialog.accept)
    buttons.addWidget(close)
    layout.addLayout(buttons)

    if not topics:
        page.setHtml("<p>The guide files are missing. Download the app again to get them.</p>")
    else:
        listing.setCurrentRow(ids.index(start_topic) if start_topic in ids else 0)
    return dialog
