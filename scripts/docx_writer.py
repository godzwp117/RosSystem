#!/usr/bin/env python3
"""build_division_docx.py -- 生成《网络安全研发分工方案 V2.docx》（纯标准库）。

为什么自己写 DOCX 构造器
------------------------
本机没有 python-docx、没有 pip、没有 LibreOffice/pandoc。而交付物要求是**真正的
Word 文件**（不是把 Markdown 改名）。DOCX 本质是一个 OOXML 包（ZIP + XML），
因此用标准库 zipfile + 手写 WordprocessingML 即可生成合规文件。

设计要点
--------
* 中文字体通过 w:rFonts 的 w:eastAsia 显式指定（宋体正文 / 黑体标题），
  避免在 Word 中显示为默认西文字体导致"中文看着不对"。
* 目录同时提供**静态目录**（任何阅读器都能看到）与 **TOC 域**（Word 中可更新页码）。
* 表格统一使用带边框的 TableGrid 样式并设置表头底纹，避免"表格断裂/无边框"。
* 页面为 A4、设置页边距；每个一级章节前插入分页符。
* 文本一律做 XML 转义，避免 & < > 破坏文档结构。

用法：
    python3 scripts/build_division_docx.py [--out docs/网络安全研发分工方案 V2.docx]
"""

from __future__ import annotations

import argparse
import os
import zipfile
from xml.sax.saxutils import escape

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
# 关系类型是**完整 URI**，不能用 R 去拼路径 —— 否则会得到
# .../relationships/officeDocument/2006/relationships/officeDocument 这种重复串，
# Word 与 python-docx 都会判定为"找不到主文档关系"。
RT_OFFICE_DOCUMENT = R + '/officeDocument'
RT_STYLES = R + '/styles'
RT_EXTENDED = R + '/extended-properties'
RT_CORE = 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
PR = 'http://schemas.openxmlformats.org/package/2006/relationships'
CP = 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
DC = 'http://purl.org/dc/elements/1.1/'
DCTERMS = 'http://purl.org/dc/terms/'
EP = 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'
VT = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'

# A4 纵向、左右页边距 1274 twips 时的可排版宽度；表格总宽不得超过它，
# 否则在 Word 中会超出正文区域，表现为表格溢出或跨页断裂。
PAGE_WIDTH_TWIPS = 11906
PAGE_MARGIN_TWIPS = 1274
USABLE_WIDTH_TWIPS = PAGE_WIDTH_TWIPS - 2 * PAGE_MARGIN_TWIPS   # 9358

BODY_FONT = '宋体'
HEAD_FONT = '黑体'
MONO_FONT = 'Consolas'
BODY_SIZE = 21          # half-points -> 10.5pt (五号)
TABLE_SIZE = 18         # 9pt


# --------------------------------------------------------------------- 组件
def _runs(text: str, bold=False, size=None, font=None, mono=False) -> str:
    """把一段文本变成 w:r（支持 **加粗** 行内标记）。"""
    font = font or (MONO_FONT if mono else BODY_FONT)
    size = size or BODY_SIZE
    parts = []
    for index, chunk in enumerate(str(text).split('**')):
        if not chunk:
            continue
        is_bold = bold or (index % 2 == 1)
        parts.append(
            '<w:r><w:rPr>'
            '<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:eastAsia="{f}"/>'
            '{b}<w:sz w:val="{s}"/><w:szCs w:val="{s}"/>'
            '</w:rPr><w:t xml:space="preserve">{t}</w:t></w:r>'.format(
                f=font, b='<w:b/><w:bCs/>' if is_bold else '', s=size,
                t=escape(chunk)))
    return ''.join(parts)


def para(text='', style=None, align=None, bold=False, size=None, font=None,
         indent=None, mono=False, space_after=None) -> str:
    props = []
    if style:
        props.append('<w:pStyle w:val="{0}"/>'.format(style))
    if align:
        props.append('<w:jc w:val="{0}"/>'.format(align))
    if indent:
        props.append('<w:ind w:left="{0}"/>'.format(indent))
    if space_after is not None:
        props.append('<w:spacing w:after="{0}"/>'.format(space_after))
    head = '<w:pPr>{0}</w:pPr>'.format(''.join(props)) if props else ''
    return '<w:p>{0}{1}</w:p>'.format(head, _runs(text, bold, size, font, mono))


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def heading(text: str, level: int) -> str:
    style = 'Heading{0}'.format(min(max(level, 1), 4))
    return ('<w:p><w:pPr><w:pStyle w:val="{0}"/><w:keepNext/>'
            '<w:outlineLvl w:val="{1}"/></w:pPr>{2}</w:p>').format(
        style, level - 1, _runs(text, font=HEAD_FONT,
                                size={1: 32, 2: 26, 3: 23, 4: 21}[min(level, 4)]))


def bullet(text: str, level: int = 0) -> str:
    marker = ['●', '○', '■'][min(level, 2)]
    return ('<w:p><w:pPr><w:ind w:left="{0}" w:hanging="240"/></w:pPr>'
            '{1}</w:p>').format(360 + level * 360,
                                _runs('{0} {1}'.format(marker, text)))


def _cell(text, width, bold=False, shading=None, align=None, size=TABLE_SIZE) -> str:
    shd = ('<w:shd w:val="clear" w:color="auto" w:fill="{0}"/>'.format(shading)
           if shading else '')
    lines = str(text).split('\n') if text is not None else ['']
    body = ''.join(
        '<w:p><w:pPr>{0}<w:spacing w:before="20" w:after="20"/></w:pPr>{1}</w:p>'.format(
            '<w:jc w:val="{0}"/>'.format(align) if align else '',
            _runs(line, bold=bold, size=size))
        for line in lines)
    return ('<w:tc><w:tcPr><w:tcW w:w="{0}" w:type="dxa"/>{1}'
            '<w:vAlign w:val="center"/></w:tcPr>{2}</w:tc>').format(width, shd, body)


def table(header, rows, widths=None, header_fill='D9E2F3', size=TABLE_SIZE) -> str:
    cols = len(header)
    widths = list(widths) if widths else [int(9000 / cols)] * cols
    if len(widths) != cols:
        widths = [int(9000 / cols)] * cols
    # 硬约束：列宽总和必须落在版心内。按比例收敛而不是直接截断，
    # 这样即使调用方算错也不会产出溢出的表格（真实解析器曾抓到过一次超宽）。
    total = sum(widths)
    if total > USABLE_WIDTH_TWIPS:
        widths = [max(400, int(w * USABLE_WIDTH_TWIPS / total)) for w in widths]
        drift = USABLE_WIDTH_TWIPS - sum(widths)
        widths[-1] += drift
    grid = ''.join('<w:gridCol w:w="{0}"/>'.format(w) for w in widths)
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
           '<w:tblW w:w="0" w:type="auto"/><w:tblLayout w:type="fixed"/>'
           '<w:tblBorders>'
           '<w:top w:val="single" w:sz="6" w:color="808080"/>'
           '<w:left w:val="single" w:sz="6" w:color="808080"/>'
           '<w:bottom w:val="single" w:sz="6" w:color="808080"/>'
           '<w:right w:val="single" w:sz="6" w:color="808080"/>'
           '<w:insideH w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '<w:insideV w:val="single" w:sz="4" w:color="BFBFBF"/>'
           '</w:tblBorders></w:tblPr><w:tblGrid>{0}</w:tblGrid>'.format(grid)]
    out.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>{0}</w:tr>'.format(
        ''.join(_cell(h, widths[i], bold=True, shading=header_fill, align='center',
                      size=size) for i, h in enumerate(header))))
    for row in rows:
        cells = list(row) + [''] * (cols - len(row))
        out.append('<w:tr>{0}</w:tr>'.format(
            ''.join(_cell(cells[i], widths[i], size=size) for i in range(cols))))
    out.append('</w:tbl>')
    # 表格后补一个空段，避免与后续内容粘连
    out.append('<w:p><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>')
    return ''.join(out)


def toc_field() -> str:
    return ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u '
            '</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            '<w:r><w:t>（在 Word 中按 F9 可更新目录页码）</w:t></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


# --------------------------------------------------------------------- 静态部件
def styles_xml() -> str:
    def style(sid, name, size, bold, font, before, after, outline=None,
              color=None):
        return ('<w:style w:type="paragraph" w:styleId="{sid}">'
                '<w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
                '<w:pPr><w:spacing w:before="{b}" w:after="{a}" w:line="300" '
                'w:lineRule="auto"/>{out}</w:pPr>'
                '<w:rPr><w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:eastAsia="{f}"/>'
                '{bo}<w:sz w:val="{s}"/><w:szCs w:val="{s}"/>{c}</w:rPr>'
                '</w:style>').format(
            sid=sid, name=name, b=before, a=after, f=font,
            bo='<w:b/><w:bCs/>' if bold else '', s=size,
            out='<w:outlineLvl w:val="{0}"/>'.format(outline) if outline is not None else '',
            c='<w:color w:val="{0}"/>'.format(color) if color else '')

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="{w}">'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:eastAsia="{f}"/>'
            '<w:sz w:val="{s}"/><w:szCs w:val="{s}"/>'
            '</w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="320" '
            'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/></w:style>'
            '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>'
            '<w:tblPr><w:tblCellMar>'
            '<w:top w:w="60" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
            '<w:bottom w:w="60" w:type="dxa"/><w:right w:w="90" w:type="dxa"/>'
            '</w:tblCellMar></w:tblPr></w:style>'
            '{h1}{h2}{h3}{h4}'
            '</w:styles>').format(
        w=W, f=BODY_FONT, s=BODY_SIZE,
        h1=style('Heading1', 'heading 1', 32, True, HEAD_FONT, 320, 160, 0, '1F3864'),
        h2=style('Heading2', 'heading 2', 26, True, HEAD_FONT, 260, 120, 1, '2E5496'),
        h3=style('Heading3', 'heading 3', 23, True, HEAD_FONT, 200, 100, 2, '2E5496'),
        h4=style('Heading4', 'heading 4', 21, True, HEAD_FONT, 160, 80, 3, '404040'))


def document_xml(body: str) -> str:
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1274" w:bottom="1440" w:left="1274" '
            'w:header="851" w:footer="992" w:gutter="0"/>'
            '<w:docGrid w:linePitch="312"/></w:sectPr>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="{w}" xmlns:r="{r}"><w:body>{b}{s}</w:body>'
            '</w:document>').format(w=W, r=R, b=body, s=sect)


def content_types_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="{ct}">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
            'package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.'
            'openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>').format(ct=CT)


def root_rels_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="{pr}">'
            '<Relationship Id="rId1" Type="{doc}" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="{core}" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="{ext}" Target="docProps/app.xml"/>'
            '</Relationships>').format(pr=PR, doc=RT_OFFICE_DOCUMENT,
                                       core=RT_CORE, ext=RT_EXTENDED)


def document_rels_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="{pr}">'
            '<Relationship Id="rId1" Type="{sty}" Target="styles.xml"/>'
            '</Relationships>').format(pr=PR, sty=RT_STYLES)


def core_xml(title: str, subject: str, author: str, created: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="{cp}" xmlns:dc="{dc}" '
            'xmlns:dcterms="{dct}" xmlns:xsi="http://www.w3.org/2001/'
            'XMLSchema-instance">'
            '<dc:title>{t}</dc:title><dc:subject>{s}</dc:subject>'
            '<dc:creator>{a}</dc:creator><cp:lastModifiedBy>{a}</cp:lastModifiedBy>'
            '<dcterms:created xsi:type="dcterms:W3CDTF">{c}</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">{c}</dcterms:modified>'
            '</cp:coreProperties>').format(cp=CP, dc=DC, dct=DCTERMS,
                                           t=escape(title), s=escape(subject),
                                           a=escape(author), c=created)


def app_xml() -> str:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="{ep}" xmlns:vt="{vt}">'
            '<Application>RosSystem 文档构建脚本</Application>'
            '<AppVersion>1.0</AppVersion></Properties>').format(ep=EP, vt=VT)


def write_docx(path: str, body: str, title: str, subject: str, author: str,
               created: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types_xml())
        z.writestr('_rels/.rels', root_rels_xml())
        z.writestr('word/document.xml', document_xml(body))
        z.writestr('word/_rels/document.xml.rels', document_rels_xml())
        z.writestr('word/styles.xml', styles_xml())
        z.writestr('docProps/core.xml', core_xml(title, subject, author, created))
        z.writestr('docProps/app.xml', app_xml())
